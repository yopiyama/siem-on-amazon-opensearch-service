# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
__copyright__ = ('Copyright Amazon.com, Inc. or its affiliates. '
                 'All Rights Reserved.')
__version__ = '2.6.2-beta.1'
__license__ = 'MIT-0'
__author__ = 'Akihiro Nakajima'
__url__ = 'https://github.com/aws-samples/siem-on-amazon-opensearch-service'

from aws_cdk import (
    aws_events,
    aws_events_targets,
    aws_iam,
    aws_kinesisfirehose,
    aws_lambda,
    aws_logs,
)
from aws_cdk import core as cdk
from aws_cdk.aws_kinesisfirehose import CfnDeliveryStream as CDS

LAMBDA_GET_WORKSPACES_INVENTORY = '''# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
__copyright__ = ('Copyright Amazon.com, Inc. or its affiliates. '
                 'All Rights Reserved.')
__version__ = '2.6.2-beta.1'
__license__ = 'MIT-0'
__author__ = 'Akihiro Nakajima'
__url__ = 'https://github.com/aws-samples/siem-on-amazon-opensearch-service'

import datetime
import gzip
import json
import os
import time

import boto3
from botocore.config import Config

config = Config(retries={'max_attempts': 10, 'mode': 'standard'})
ws_client = boto3.client('workspaces', config=config)
s3_resource = boto3.resource('s3')
bucket = s3_resource.Bucket(os.environ['log_bucket_name'])
AWS_ID = str(boto3.client("sts").get_caller_identity()["Account"])
AWS_REGION = os.environ['AWS_DEFAULT_REGION']


def lambda_handler(event, context):
    num = 0
    now = datetime.datetime.now()
    file_name = f'workspaces-inventory-{now.strftime("%Y%m%d_%H%M%S")}.json.gz'
    s3file_name = (
        f'AWSLogs/{AWS_ID}/WorkSpaces/Inventory/{AWS_REGION}/'
        f'{now.strftime("%Y/%m/%d")}/{file_name}')
    f = gzip.open(f'/tmp/{file_name}', 'tw')

    api = 'describe_workspaces_connection_status'
    print(api)
    ws_cons = {}
    num = 0
    paginator = ws_client.get_paginator(api)
    for response in paginator.paginate():
        for ws_con in response['WorkspacesConnectionStatus']:
            ws_cons[ws_con['WorkspaceId']] = ws_con
            num += 1
        time.sleep(0.75)
    print(f'Number of {api}: {num}')

    api = 'describe_workspaces'
    print(api)
    num = 0
    paginator = ws_client.get_paginator(api)
    response_iterator = paginator.paginate(PaginationConfig={'PageSize': 25})
    for response in response_iterator:
        print(f'{response["ResponseMetadata"]["RequestId"]}: '
              f'{len(response["Workspaces"])}')
        dt = datetime.datetime.strptime(
            response['ResponseMetadata']['HTTPHeaders']['date'],
            "%a, %d %b %Y %H:%M:%S GMT")
        jsonobj = {
            'id': response['ResponseMetadata']['RequestId'],
            'time': dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
            'detail-type': 'WorkSpaces Fake',
            "source": "aws.fake.workspaces",
            "account": AWS_ID,
            'region': AWS_REGION,
            "resources": [],
            'detail': {'Workspaces': []}}
        for item in response['Workspaces']:
            try:
                item = {**item, **ws_cons[item['WorkspaceId']]}
            except Exception:
                pass
            jsonobj['detail']['Workspaces'].append(item)
        num += len(response['Workspaces'])
        f.write(json.dumps(jsonobj, default=str))
        f.flush()
        # sleep 0.75 second to avoid reaching AWS API rate limit (2rps)
        time.sleep(0.75)
    print(f'Total nummber of WorkSpaces inventory: {num}')

    f.close()
    print(f'Upload path: s3://{bucket.name}/{s3file_name}')
    bucket.upload_file(f'/tmp/{file_name}', s3file_name)
'''


LAMBDA_GET_TRUSTEDADVISOR_CHECK_RESULT = '''# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
__copyright__ = 'Amazon.com, Inc. or its affiliates'
__version__ = '2.6.1-beta.2'
__license__ = 'MIT-0'
__author__ = 'Katsuya Matsuoka'
__url__ = 'https://github.com/aws-samples/siem-on-amazon-opensearch-service'

import datetime
import gzip
import json
import os
import time

import boto3
import botocore.exceptions

client = boto3.Session(region_name='us-east-1').client('support')
s3_resource = boto3.resource('s3')
bucket = s3_resource.Bucket(os.environ['log_bucket_name'])
AWS_ID = str(boto3.client("sts").get_caller_identity()["Account"])
AWS_REGION = os.environ['AWS_DEFAULT_REGION']
is_enable_japanese = (
    os.environ['enable_japanese_description'] == 'Yes')

checks_response = client.describe_trusted_advisor_checks(language='en')
if is_enable_japanese:
    checks_ja = {}
    for check_ja in client.describe_trusted_advisor_checks(
            language='ja')['checks']:
        checks_ja[check_ja['id']] = check_ja


def execute_check():
    check_ids = []
    unrefreshable_check_ids = []
    for check in checks_response['checks']:
        check_id = check['id']
        check_ids.append(check_id)
        try:
            client.refresh_trusted_advisor_check(checkId=check_id)
        except botocore.exceptions.ClientError as err:
            if err.response['Error']['Code'] == \
                    'InvalidParameterValueException':
                unrefreshable_check_ids.append(check_id)
            else:
                print(err)
    return check_ids, unrefreshable_check_ids


def wait_check_completion(check_ids):
    count = 0
    while True:
        response = client.describe_trusted_advisor_check_refresh_statuses(
            checkIds=check_ids)
        all_done = True
        for status in response['statuses']:
            all_done &= (status['status'] in ['abandoned', 'none', 'success'])
        if all_done:
            break
        count += 1
        if count > 2:
            break
        time.sleep(30)


def lambda_handler(event, context):
    now = datetime.datetime.now()
    file_name = (
        'trustedadvisor-check-results-'
        f'{now.strftime("%Y%m%d_%H%M%S")}.json.gz')
    s3file_name = (
        f'AWSLogs/{AWS_ID}/TrustedAdvisor/{AWS_REGION}/'
        f'{now.strftime("%Y/%m/%d")}/{file_name}')
    f = gzip.open(f'/tmp/{file_name}', 'tw')
    print('Total nummber of checks: '
          f'{len(checks_response["checks"])}')

    check_ids, unrefreshable_check_ids = execute_check()
    wait_check_completion(check_ids)

    for check in checks_response['checks']:
        check_id = check['id']
        response = client.describe_trusted_advisor_check_result(
            checkId=check_id)
        dt = datetime.datetime.strptime(
            response['ResponseMetadata']['HTTPHeaders']['date'],
            "%a, %d %b %Y %H:%M:%S GMT")
        jsonobj = {
            'id': response['ResponseMetadata']['RequestId'],
            'time': dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "account": AWS_ID,
            'region': AWS_REGION,
            "resources": [],
            'check': check,
            'result': response['result'],
            'refreshable': check_id not in unrefreshable_check_ids}
        if is_enable_japanese:
            jsonobj['check_ja'] = checks_ja[check_id]
        if 'flaggedResources' in response['result'] and \
                len(response['result']['flaggedResources']) > 0:
            resource_num = len(response['result']['flaggedResources'])
            for i in range(resource_num):
                jsonobj['result']['flaggedResource'] = \
                    response['result']['flaggedResources'][i]
                jsonobj['result']['flaggedResource']['number'] = i + 1
                f.write(json.dumps(jsonobj, ensure_ascii=False))
                f.flush()
        else:
            f.write(json.dumps(jsonobj, ensure_ascii=False))
            f.flush()
    f.close()
    print(f'Upload path: s3://{bucket.name}/{s3file_name}')
    bucket.upload_file(f'/tmp/{file_name}', s3file_name)
'''


class FirehoseExporterStack(cdk.Stack):
    def __init__(self, scope: cdk.Construct, construct_id: str,
                 default_firehose_name='siem-XXXXXXXXXXX-to-s3',
                 firehose_compression_format='UNCOMPRESSED',
                 **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        log_bucket_name = cdk.Fn.import_value('sime-log-bucket-name')
        role_name_kdf_to_s3 = cdk.Fn.import_value(
            'siem-kdf-to-s3-role-name')

        kdf_name = cdk.CfnParameter(
            self, 'FirehoseName',
            description=('New Kinesis Data Firehose Name to deliver log. '
                         'modify XXXXXXXXX'),
            default=default_firehose_name)
        kdf_buffer_size = cdk.CfnParameter(
            self, 'FirehoseBufferSize', type='Number',
            description='Enter a buffer size between 1 - 128 (MiB)',
            default=1, min_value=1, max_value=128)
        kdf_buffer_interval = cdk.CfnParameter(
            self, 'FirehoseBufferInterval', type='Number',
            description='Enter a buffer interval between 60 - 900 (seconds.)',
            default=60, min_value=60, max_value=900)
        s3_desitination_prefix = cdk.CfnParameter(
            self, 'S3DestPrefix',
            description='S3 destination prefix',
            default='AWSLogs/YourAccuntId/LogType/Region/')

        self.kdf_to_s3 = aws_kinesisfirehose.CfnDeliveryStream(
            self, "Kdf",
            delivery_stream_name=kdf_name.value_as_string,
            s3_destination_configuration=CDS.S3DestinationConfigurationProperty(
                bucket_arn=f'arn:aws:s3:::{log_bucket_name}',
                prefix=s3_desitination_prefix.value_as_string,
                buffering_hints=CDS.BufferingHintsProperty(
                    interval_in_seconds=kdf_buffer_interval.value_as_number,
                    size_in_m_bs=kdf_buffer_size.value_as_number),
                compression_format=firehose_compression_format,
                role_arn=(f'arn:aws:iam::{cdk.Aws.ACCOUNT_ID}:role/'
                          f'service-role/{role_name_kdf_to_s3}')
            )
        )


class CWLNoCompressExporterStack(cdk.Stack):
    def __init__(self, scope: cdk.Construct, construct_id: str,
                 **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        log_bucket_name = cdk.Fn.import_value('sime-log-bucket-name')
        role_name_cwl_to_kdf = cdk.Fn.import_value(
            'siem-cwl-to-kdf-role-name')
        role_name_kdf_to_s3 = cdk.Fn.import_value(
            'siem-kdf-to-s3-role-name')

        kdf_name = cdk.CfnParameter(
            self, 'KdfName',
            description='New Kinesis Data Firehose Name to deliver CWL event',
            default='siem-XXXXXXXXXXX-to-s3')
        kdf_buffer_size = cdk.CfnParameter(
            self, 'KdfBufferSize', type='Number',
            description='Enter a buffer size between 1 - 128 (MiB)',
            default=1, min_value=1, max_value=128)
        kdf_buffer_interval = cdk.CfnParameter(
            self, 'KdfBufferInterval', type='Number',
            description='Enter a buffer interval between 60 - 900 (seconds.)',
            default=60, min_value=60, max_value=900)
        cwl_loggroup_name = cdk.CfnParameter(
            self, 'CwlLogGroupName',
            description='Existing CloudWatch Logs group name',
            default='/aws/XXXXXXXXXXXXXXXXX')
        s3_desitination_prefix = cdk.CfnParameter(
            self, 'S3DestPrefix',
            description='S3 destination prefix',
            default='AWSLogs/YourAccuntId/LogType/Region/')

        kdf_to_s3 = aws_kinesisfirehose.CfnDeliveryStream(
            self, "Kdf",
            delivery_stream_name=kdf_name.value_as_string,
            s3_destination_configuration=CDS.S3DestinationConfigurationProperty(
                bucket_arn=f'arn:aws:s3:::{log_bucket_name}',
                prefix=s3_desitination_prefix.value_as_string,
                buffering_hints=CDS.BufferingHintsProperty(
                    interval_in_seconds=kdf_buffer_interval.value_as_number,
                    size_in_m_bs=kdf_buffer_size.value_as_number),
                compression_format='UNCOMPRESSED',
                role_arn=(f'arn:aws:iam::{cdk.Aws.ACCOUNT_ID}:role/'
                          f'service-role/{role_name_kdf_to_s3}')
            )
        )

        aws_logs.CfnSubscriptionFilter(
            self, 'KinesisSubscription',
            destination_arn=kdf_to_s3.attr_arn,
            filter_pattern='',
            log_group_name=cwl_loggroup_name.value_as_string,
            role_arn=(f'arn:aws:iam::{cdk.Aws.ACCOUNT_ID}:role/'
                      f'{role_name_cwl_to_kdf}')
        )


class EventBridgeEventsExporterStack(cdk.Stack):
    def __init__(self, scope: cdk.Construct, construct_id: str,
                 **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        log_bucket_name = cdk.Fn.import_value('sime-log-bucket-name')
        role_name_kdf_to_s3 = cdk.Fn.import_value(
            'siem-kdf-to-s3-role-name')

        kdf_name = cdk.CfnParameter(
            self, 'KdfName',
            description=(
                'New Kinesis Data Firehose Name to deliver EventBridge Events '
                'to S3 bucket. This Firehose will be created'),
            default='siem-eventbridge-events-to-s3')
        kdf_buffer_size = cdk.CfnParameter(
            self, 'KdfBufferSize', type='Number',
            description='Enter a buffer size between 64 - 128 (MiB)',
            default=64, min_value=64, max_value=128)
        kdf_buffer_interval = cdk.CfnParameter(
            self, 'KdfBufferInterval', type='Number',
            description='Enter a buffer interval between 60 - 900 (seconds.)',
            default=60, min_value=60, max_value=900)
        load_security_hub = cdk.CfnParameter(
            self, 'LoadSecurtyHub',
            description=('Do you enable to load SecurityHub events to '
                         'OpenSearch Service?'),
            allowed_values=['Yes', 'No'], default='Yes')
        load_config_rules = cdk.CfnParameter(
            self, 'LoadConfigRules',
            description=('Do you enable to load Config Rules events to '
                         'OpenSearch Service?'),
            allowed_values=['Yes', 'No'], default='Yes')
        s3_desitination_prefix = cdk.CfnParameter(
            self, 'S3DestPrefix',
            description='S3 destination prefix',
            default='AWSLogs/')

        self.template_options.metadata = {
            'AWS::CloudFormation::Interface': {
                'ParameterGroups': [
                    {'Label': {'default': 'Amazon Kinesis Data Firehose'},
                     'Parameters': [kdf_name.logical_id,
                                    s3_desitination_prefix.logical_id,
                                    kdf_buffer_size.logical_id,
                                    kdf_buffer_interval.logical_id]},
                    {'Label': {'default': 'Events'},
                     'Parameters': [load_security_hub.logical_id,
                                    load_config_rules.logical_id]}]}}

        kdf_to_s3 = aws_kinesisfirehose.CfnDeliveryStream(
            self, "Kdf",
            delivery_stream_name=kdf_name.value_as_string,
            extended_s3_destination_configuration=CDS.ExtendedS3DestinationConfigurationProperty(
                # Destination settings
                bucket_arn=f'arn:aws:s3:::{log_bucket_name}',

                error_output_prefix="ErrorLogs/",
                prefix=(s3_desitination_prefix.value_as_string + "!{partitionKeyFromQuery:account}/!{partitionKeyFromQuery:service}/!{partitionKeyFromQuery:detailtype}/!{partitionKeyFromQuery:region}/!{timestamp:yyyy}/!{timestamp:MM}/!{timestamp:dd}/"),
                buffering_hints=CDS.BufferingHintsProperty(
                    interval_in_seconds=kdf_buffer_interval.value_as_number,
                    size_in_m_bs=kdf_buffer_size.value_as_number),
                compression_format='GZIP',
                dynamic_partitioning_configuration=aws_kinesisfirehose.CfnDeliveryStream.DynamicPartitioningConfigurationProperty(
                    enabled=True,
                    retry_options=aws_kinesisfirehose.CfnDeliveryStream.RetryOptionsProperty(
                        duration_in_seconds=30)
                ),
                processing_configuration=aws_kinesisfirehose.CfnDeliveryStream.ProcessingConfigurationProperty(
                    enabled=True,
                    processors=[
                        aws_kinesisfirehose.CfnDeliveryStream.ProcessorProperty(
                            type="MetadataExtraction",
                            parameters=[
                                aws_kinesisfirehose.CfnDeliveryStream.ProcessorParameterProperty(
                                    parameter_name="MetadataExtractionQuery",
                                    parameter_value="""{service: .source, account: .account, region: .region, detailtype: ."detail-type"| gsub(" "; "_")}"""),
                                aws_kinesisfirehose.CfnDeliveryStream.ProcessorParameterProperty(
                                    parameter_name="JsonParsingEngine",
                                    parameter_value="JQ-1.6")

                            ]
                        )
                    ]
                ),
                # Permissions
                role_arn=(f'arn:aws:iam::{cdk.Aws.ACCOUNT_ID}:role/'
                          f'service-role/{role_name_kdf_to_s3}'),
            )
        )

        is_security_hub = cdk.CfnCondition(
            self, "IsSecurityHub",
            expression=cdk.Fn.condition_equals(load_security_hub.value_as_string, "Yes"))
        rule_security_hub = aws_events.Rule(
            self, "RuleSecurityHub", rule_name='siem-securityhub-to-firehose',
            description=f'SIEM on OpenSearch Service v{__version__}:',
            event_pattern=aws_events.EventPattern(
                source=["aws.securityhub"],
                detail_type=["Security Hub Findings - Imported"]))
        rule_security_hub.node.default_child.cfn_options.condition = is_security_hub
        rule_security_hub.add_target(aws_events_targets.KinesisFirehoseStream(kdf_to_s3))

        is_config_rules = cdk.CfnCondition(
            self, "IsConfigRules",
            expression=cdk.Fn.condition_equals(load_config_rules.value_as_string, "Yes"))
        rule_config_rules = aws_events.Rule(
            self, "RuleConfigRules", rule_name='siem-configrules-to-firehose',
            description=f'SIEM on OpenSearch Service v{__version__}:',
            event_pattern=aws_events.EventPattern(
                source=["aws.config"],
                detail_type=["Config Rules Compliance Change"]))
        rule_config_rules.node.default_child.cfn_options.condition = is_config_rules
        rule_config_rules.add_target(aws_events_targets.KinesisFirehoseStream(kdf_to_s3))


class ADLogExporterStack(cdk.Stack):
    def __init__(self, scope: cdk.Construct, construct_id: str,
                 **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        log_bucket_name = cdk.Fn.import_value('sime-log-bucket-name')
        role_name_cwl_to_kdf = cdk.Fn.import_value(
            'siem-cwl-to-kdf-role-name')
        role_name_kdf_to_s3 = cdk.Fn.import_value(
            'siem-kdf-to-s3-role-name')

        kdf_ad_name = cdk.CfnParameter(
            self, 'KdfAdName',
            description='Kinesis Data Firehose Name to deliver AD event',
            default='siem-ad-event-to-s3')
        kdf_buffer_size = cdk.CfnParameter(
            self, 'KdfBufferSize', type='Number',
            description='Enter a buffer size between 1 - 128 (MiB)',
            default=1, min_value=1, max_value=128)
        kdf_buffer_interval = cdk.CfnParameter(
            self, 'KdfBufferInterval', type='Number',
            description='Enter a buffer interval between 60 - 900 (seconds.)',
            default=60, min_value=60, max_value=900)
        cwl_ad_name = cdk.CfnParameter(
            self, 'CwlAdName',
            description='CloudWatch Logs group name',
            default='/aws/directoryservice/d-XXXXXXXXXXXXXXXXX')

        kdf_to_s3 = aws_kinesisfirehose.CfnDeliveryStream(
            self, "KDFForAdEventLog",
            delivery_stream_name=kdf_ad_name.value_as_string,
            s3_destination_configuration=CDS.S3DestinationConfigurationProperty(
                bucket_arn=f'arn:aws:s3:::{log_bucket_name}',
                prefix=f'AWSLogs/{cdk.Aws.ACCOUNT_ID}/DirectoryService/MicrosoftAD/',
                buffering_hints=CDS.BufferingHintsProperty(
                    interval_in_seconds=kdf_buffer_interval.value_as_number,
                    size_in_m_bs=kdf_buffer_size.value_as_number),
                compression_format='UNCOMPRESSED',
                role_arn=(f'arn:aws:iam::{cdk.Aws.ACCOUNT_ID}:role/'
                          f'service-role/{role_name_kdf_to_s3}')
            )
        )

        aws_logs.CfnSubscriptionFilter(
            self, 'KinesisSubscription',
            destination_arn=kdf_to_s3.attr_arn,
            filter_pattern='',
            log_group_name=cwl_ad_name.value_as_string,
            role_arn=(f'arn:aws:iam::{cdk.Aws.ACCOUNT_ID}:role/'
                      f'{role_name_cwl_to_kdf}')
        )


class WorkSpacesLogExporterStack(cdk.Stack):
    def __init__(self, scope: cdk.Construct, construct_id: str,
                 **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        log_bucket_name = cdk.Fn.import_value('sime-log-bucket-name')
        service_role_kdf_to_s3 = cdk.Fn.import_value(
            'siem-kdf-to-s3-role-name')

        cwe_frequency = cdk.CfnParameter(
            self, 'cweRulesFrequency', type='Number',
            description=(
                'How often do you get WorkSpaces Inventory? (every minutes)'),
            default=720)
        kdf_workspaces_name = cdk.CfnParameter(
            self, 'KdfWorkSpacesName',
            description=(
                'Kinesis Data Firehose Name to deliver workspaces event'),
            default='siem-workspaces-event-to-s3',)
        kdf_buffer_size = cdk.CfnParameter(
            self, 'KdfBufferSize', type='Number',
            description='Enter a buffer size between 1 - 128 (MiB)',
            default=1, min_value=1, max_value=128)
        kdf_buffer_interval = cdk.CfnParameter(
            self, 'KdfBufferInterval', type='Number',
            description='Enter a buffer interval between 60 - 900 (seconds.)',
            default=60, min_value=60, max_value=900)

        role_get_workspaces_inventory = aws_iam.Role(
            self, 'getWorkspacesInventoryRole',
            role_name='siem-get-workspaces-inventory-role',
            inline_policies={
                'describe-workspaces': aws_iam.PolicyDocument(
                    statements=[
                        aws_iam.PolicyStatement(
                            actions=['workspaces:Describe*'], resources=['*'],
                            sid='DescribeWorkSpacesPolicyGeneratedBySiemCfn')
                    ]
                ),
                'firehose-to-s3': aws_iam.PolicyDocument(
                    statements=[
                        aws_iam.PolicyStatement(
                            actions=['s3:PutObject'],
                            resources=[f'arn:aws:s3:::{log_bucket_name}/*'],
                            sid='FirehoseToS3PolicyGeneratedBySiemCfn'
                        )
                    ]
                )
            },
            managed_policies=[
                aws_iam.ManagedPolicy.from_aws_managed_policy_name(
                    'service-role/AWSLambdaBasicExecutionRole'),
            ],
            assumed_by=aws_iam.ServicePrincipal('lambda.amazonaws.com')
        )

        # Lambda Functions to get workspaces inventory
        lambda_func = aws_lambda.Function(
            self, 'lambdaGetWorkspacesInventory',
            runtime=aws_lambda.Runtime.PYTHON_3_9,
            code=aws_lambda.InlineCode(LAMBDA_GET_WORKSPACES_INVENTORY),
            function_name='siem-get-workspaces-inventory',
            description='SIEM: get workspaces inventory',
            handler='index.lambda_handler',
            memory_size=160,
            timeout=cdk.Duration.seconds(600),
            role=role_get_workspaces_inventory,
            environment={'log_bucket_name': log_bucket_name}
        )
        rule = aws_events.Rule(
            self, 'eventBridgeRuleWorkSpaceInventory',
            rule_name='siem-workspaces-inventory-to-lambda',
            schedule=aws_events.Schedule.rate(
                cdk.Duration.minutes(cwe_frequency.value_as_number)))
        rule.add_target(aws_events_targets.LambdaFunction(lambda_func))

        kdf_to_s3 = aws_kinesisfirehose.CfnDeliveryStream(
            self, "KDFForWorkSpacesEvent",
            delivery_stream_name=kdf_workspaces_name.value_as_string,
            s3_destination_configuration=CDS.S3DestinationConfigurationProperty(
                bucket_arn=f'arn:aws:s3:::{log_bucket_name}',
                prefix=f'AWSLogs/{cdk.Aws.ACCOUNT_ID}/WorkSpaces/Event/',
                compression_format='GZIP',
                buffering_hints=CDS.BufferingHintsProperty(
                    interval_in_seconds=kdf_buffer_interval.value_as_number,
                    size_in_m_bs=kdf_buffer_size.value_as_number),
                role_arn=(f'arn:aws:iam::{cdk.Aws.ACCOUNT_ID}:role/'
                          f'service-role/{service_role_kdf_to_s3}')
            )
        )

        pattern = aws_events.EventPattern(
            detail_type=["WorkSpaces Access"], source=['aws.workspaces'])

        aws_events.Rule(
            self, 'eventBridgeRuleWorkSpacesEvent', event_pattern=pattern,
            rule_name='siem-workspaces-event-to-kdf',
            targets=[aws_events_targets.KinesisFirehoseStream(kdf_to_s3)])


class TrustedAdvisorLogExporterStack(cdk.Stack):
    def __init__(self, scope: cdk.Construct, construct_id: str,
                 **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        log_bucket_name = cdk.Fn.import_value('sime-log-bucket-name')

        cwe_frequency = cdk.CfnParameter(
            self, 'cweRulesFrequency', type='Number',
            description=(
                'How often do you get TrustedAdvisor check result? (every minutes)'),
            default=720)
        enable_japanese_description = cdk.CfnParameter(
            self, 'enableJapaneseDescription',
            description=(
                'Do you enable Japanese check descriptino in addition to English?'),
            allowed_values=['Yes', 'No'], default='Yes')

        role_get_trustedadvisor_check_result = aws_iam.Role(
            self, 'getTrustedAdvisorCheckResultRole',
            role_name='siem-get-trustedadvisor-check-result-role',
            inline_policies={
                'describe-trustedadvisor': aws_iam.PolicyDocument(
                    statements=[
                        aws_iam.PolicyStatement(
                            actions=[
                                'support:DescribeTrustedAdvisorCheck*',
                                'support:RefreshTrustedAdvisorCheck'
                            ],
                            resources=['*'],
                            sid='DescribeTrustedAdvisorPolicyGeneratedBySiemCfn')
                    ]
                ),
                'lambda-to-s3': aws_iam.PolicyDocument(
                    statements=[
                        aws_iam.PolicyStatement(
                            actions=['s3:PutObject'],
                            resources=[f'arn:aws:s3:::{log_bucket_name}/*'],
                            sid='LambdaToS3PolicyGeneratedBySiemCfn'
                        )
                    ]
                )
            },
            managed_policies=[
                aws_iam.ManagedPolicy.from_aws_managed_policy_name(
                    'service-role/AWSLambdaBasicExecutionRole'),
            ],
            assumed_by=aws_iam.ServicePrincipal('lambda.amazonaws.com')
        )

        # Lambda Functions to get trustedadvisor check result
        lambda_func = aws_lambda.Function(
            self, 'lambdaGetTrustedAdvisorCheckResult',
            runtime=aws_lambda.Runtime.PYTHON_3_8,
            code=aws_lambda.InlineCode(LAMBDA_GET_TRUSTEDADVISOR_CHECK_RESULT),
            function_name='siem-get-trustedadvisor-check-result',
            description='SIEM: get trustedadvisor check result',
            handler='index.lambda_handler',
            timeout=cdk.Duration.seconds(600),
            role=role_get_trustedadvisor_check_result,
            environment={
                'log_bucket_name': log_bucket_name,
                'enable_japanese_description': enable_japanese_description.value_as_string}
        )
        rule = aws_events.Rule(
            self, 'eventBridgeRuleTrustedAdvisorCheckResult',
            rule_name='siem-trustedadvisor-check-result-to-lambda',
            schedule=aws_events.Schedule.rate(
                cdk.Duration.minutes(cwe_frequency.value_as_number)))
        rule.add_target(aws_events_targets.LambdaFunction(lambda_func))


class CoreLogExporterStack(cdk.Stack):
    def __init__(self, scope: cdk.Construct, construct_id: str,
                 **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        log_bucket_name = cdk.CfnParameter(
            self, 'siemLogBucketName',
            description=('S3 Bucket name which store logs to load SIEM. '
                         'Replace 111111111111 to your AWS account'),
            default='aes-siem-111111111111-log')
        role_name_cwl_to_kdf = cdk.CfnParameter(
            self, 'roleNameCwlToKdf',
            description=('role name for CloudWatch Logs to send data to '
                         'Kinsis Data Firehose. Replace YOUR-REGION'),
            default='siem-role-cwl-to-firehose-YOUR-REGION')
        role_name_kdf_to_s3 = cdk.CfnParameter(
            self, 'roleNameKdfToS3',
            description=('role name for Kinesis Data Firehose to send data '
                         'to S3. Replace YOUR-REGION'),
            default='siem-role-firehose-to-s3-YOUR-REGION')

        bucket_arn = f'arn:aws:s3:::{log_bucket_name.value_as_string}'

        role_cwl_to_kdf = aws_iam.Role(
            self, 'cwlRole',
            role_name=role_name_cwl_to_kdf.value_as_string,
            inline_policies={
                'cwl-to-firehose': aws_iam.PolicyDocument(
                    statements=[
                        aws_iam.PolicyStatement(
                            actions=["firehose:*"],
                            resources=[(f'arn:aws:firehose:{cdk.Aws.REGION}:'
                                        f'{cdk.Aws.ACCOUNT_ID}:*')],
                            sid='CwlToFirehosePolicyGeneratedBySiemCfn'
                        )
                    ]
                )
            },
            assumed_by=aws_iam.ServicePrincipal(
                f'logs.{cdk.Aws.REGION}.amazonaws.com'))

        role_kdf_to_s3 = aws_iam.Role(
            self, 'firehoseRole', path='/service-role/',
            role_name=role_name_kdf_to_s3.value_as_string,
            inline_policies={
                'firehose-to-s3': aws_iam.PolicyDocument(
                    statements=[
                        aws_iam.PolicyStatement(
                            sid='FirehoseToS3PolicyGeneratedBySiemCfn',
                            actions=["s3:AbortMultipartUpload",
                                     "s3:GetBucketLocation",
                                     "s3:GetObject",
                                     "s3:ListBucket",
                                     "s3:ListBucketMultipartUploads",
                                     "s3:PutObject"],
                            resources=[f'{bucket_arn}',
                                       f'{bucket_arn}/*'])]),
                'for-logigng': aws_iam.PolicyDocument(
                    statements=[
                        aws_iam.PolicyStatement(
                            sid='LoggingPolicyGeneratedBySiemCfn',
                            actions=["logs:PutLogEvents"],
                            resources=[(f'arn:aws:logs:{cdk.Aws.REGION}:'
                                        f'{cdk.Aws.ACCOUNT_ID}:log-group:/aws/'
                                        f'kinesisfirehose/*:log-stream:*')])],
                ),
            },
            assumed_by=aws_iam.ServicePrincipal('firehose.amazonaws.com'))

        ######################################################################
        # output for cross stack
        ######################################################################
        cdk.CfnOutput(self, 'logBucketName',
                      export_name='sime-log-bucket-name',
                      value=log_bucket_name.value_as_string)
        cdk.CfnOutput(self, 'cwlRoleName',
                      export_name='siem-cwl-to-kdf-role-name',
                      value=role_cwl_to_kdf.role_name)
        cdk.CfnOutput(self, 'kdfRoleName',
                      export_name='siem-kdf-to-s3-role-name',
                      value=role_kdf_to_s3.role_name)


class DeploymentSamplesStack(cdk.Stack):
    def __init__(self, scope: cdk.Construct, construct_id: str,
                 **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # The code that defines your stack goes here
