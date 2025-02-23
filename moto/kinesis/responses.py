from __future__ import unicode_literals

import json

from moto.core.responses import BaseResponse
from .models import kinesis_backends


class KinesisResponse(BaseResponse):
    @property
    def parameters(self):
        return json.loads(self.body)

    @property
    def kinesis_backend(self):
        return kinesis_backends[self.region]

    @property
    def is_firehose(self):
        host = self.headers.get("host") or self.headers["Host"]
        return host.startswith("firehose") or "firehose" in self.headers.get(
            "Authorization", ""
        )

    def create_stream(self):
        stream_name = self.parameters.get("StreamName")
        shard_count = self.parameters.get("ShardCount")
        retention_period_hours = self.parameters.get("RetentionPeriodHours")
        self.kinesis_backend.create_stream(
            stream_name, shard_count, retention_period_hours, self.region
        )
        return ""

    def describe_stream(self):
        stream_name = self.parameters.get("StreamName")
        stream = self.kinesis_backend.describe_stream(stream_name)
        return json.dumps(stream.to_json())

    def describe_stream_summary(self):
        stream_name = self.parameters.get("StreamName")
        stream = self.kinesis_backend.describe_stream_summary(stream_name)
        return json.dumps(stream.to_json_summary())

    def list_streams(self):
        streams = self.kinesis_backend.list_streams()
        stream_names = [stream.stream_name for stream in streams]
        max_streams = self._get_param("Limit", 10)
        try:
            token = self.parameters.get("ExclusiveStartStreamName")
        except ValueError:
            token = self._get_param("ExclusiveStartStreamName")
        if token:
            start = stream_names.index(token) + 1
        else:
            start = 0
        streams_resp = stream_names[start : start + max_streams]
        has_more_streams = False
        if start + max_streams < len(stream_names):
            has_more_streams = True

        return json.dumps(
            {"HasMoreStreams": has_more_streams, "StreamNames": streams_resp}
        )

    def delete_stream(self):
        stream_name = self.parameters.get("StreamName")
        self.kinesis_backend.delete_stream(stream_name)
        return ""

    def get_shard_iterator(self):
        stream_name = self.parameters.get("StreamName")
        shard_id = self.parameters.get("ShardId")
        shard_iterator_type = self.parameters.get("ShardIteratorType")
        starting_sequence_number = self.parameters.get("StartingSequenceNumber")
        at_timestamp = self.parameters.get("Timestamp")

        shard_iterator = self.kinesis_backend.get_shard_iterator(
            stream_name,
            shard_id,
            shard_iterator_type,
            starting_sequence_number,
            at_timestamp,
        )

        return json.dumps({"ShardIterator": shard_iterator})

    def get_records(self):
        shard_iterator = self.parameters.get("ShardIterator")
        limit = self.parameters.get("Limit")

        (
            next_shard_iterator,
            records,
            millis_behind_latest,
        ) = self.kinesis_backend.get_records(shard_iterator, limit)

        return json.dumps(
            {
                "NextShardIterator": next_shard_iterator,
                "Records": [record.to_json() for record in records],
                "MillisBehindLatest": millis_behind_latest,
            }
        )

    def put_record(self):
        if self.is_firehose:
            return self.firehose_put_record()
        stream_name = self.parameters.get("StreamName")
        partition_key = self.parameters.get("PartitionKey")
        explicit_hash_key = self.parameters.get("ExplicitHashKey")
        sequence_number_for_ordering = self.parameters.get("SequenceNumberForOrdering")
        data = self.parameters.get("Data")

        sequence_number, shard_id = self.kinesis_backend.put_record(
            stream_name,
            partition_key,
            explicit_hash_key,
            sequence_number_for_ordering,
            data,
        )

        return json.dumps({"SequenceNumber": sequence_number, "ShardId": shard_id})

    def put_records(self):
        if self.is_firehose:
            return self.put_record_batch()
        stream_name = self.parameters.get("StreamName")
        records = self.parameters.get("Records")

        response = self.kinesis_backend.put_records(stream_name, records)

        return json.dumps(response)

    def split_shard(self):
        stream_name = self.parameters.get("StreamName")
        shard_to_split = self.parameters.get("ShardToSplit")
        new_starting_hash_key = self.parameters.get("NewStartingHashKey")
        self.kinesis_backend.split_shard(
            stream_name, shard_to_split, new_starting_hash_key
        )
        return ""

    def merge_shards(self):
        stream_name = self.parameters.get("StreamName")
        shard_to_merge = self.parameters.get("ShardToMerge")
        adjacent_shard_to_merge = self.parameters.get("AdjacentShardToMerge")
        self.kinesis_backend.merge_shards(
            stream_name, shard_to_merge, adjacent_shard_to_merge
        )
        return ""

    def increase_stream_retention_period(self):
        stream_name = self.parameters.get("StreamName")
        retention_period_hours = self.parameters.get("RetentionPeriodHours")
        self.kinesis_backend.increase_stream_retention_period(
            stream_name, retention_period_hours
        )
        return ""

    def decrease_stream_retention_period(self):
        stream_name = self.parameters.get("StreamName")
        retention_period_hours = self.parameters.get("RetentionPeriodHours")
        self.kinesis_backend.decrease_stream_retention_period(
            stream_name, retention_period_hours
        )
        return ""

    """ Firehose """

    def create_delivery_stream(self):
        stream_name = self.parameters["DeliveryStreamName"]
        redshift_config = self.parameters.get("RedshiftDestinationConfiguration")
        s3_config = self.parameters.get("S3DestinationConfiguration")
        extended_s3_config = self.parameters.get("ExtendedS3DestinationConfiguration")
        elasticsearch_config = self.parameters.get(
            "ElasticsearchDestinationConfiguration"
        )

        if redshift_config:
            redshift_s3_config = redshift_config["S3Configuration"]
            stream_kwargs = {
                "redshift_username": redshift_config["Username"],
                "redshift_password": redshift_config["Password"],
                "redshift_jdbc_url": redshift_config["ClusterJDBCURL"],
                "redshift_role_arn": redshift_config["RoleARN"],
                "redshift_copy_command": redshift_config["CopyCommand"],
                "redshift_s3_role_arn": redshift_s3_config["RoleARN"],
                "redshift_s3_bucket_arn": redshift_s3_config["BucketARN"],
                "redshift_s3_prefix": redshift_s3_config["Prefix"],
                "redshift_s3_compression_format": redshift_s3_config.get(
                    "CompressionFormat"
                ),
                "redshift_s3_buffering_hints": redshift_s3_config["BufferingHints"],
            }
        elif s3_config:
            stream_kwargs = {"s3_config": s3_config}
        elif extended_s3_config:
            stream_kwargs = {"extended_s3_config": extended_s3_config}
        elif elasticsearch_config:
            stream_kwargs = {"elasticsearch_config": elasticsearch_config}
        else:
            stream_kwargs = {}

        stream = self.kinesis_backend.create_delivery_stream(
            stream_name, **stream_kwargs
        )
        return json.dumps({"DeliveryStreamARN": stream.arn})

    def describe_delivery_stream(self):
        stream_name = self.parameters["DeliveryStreamName"]
        stream = self.kinesis_backend.get_delivery_stream(stream_name)
        return json.dumps(stream.to_dict())

    def list_delivery_streams(self):
        streams = self.kinesis_backend.list_delivery_streams()
        return json.dumps(
            {
                "DeliveryStreamNames": [stream.name for stream in streams],
                "HasMoreDeliveryStreams": False,
            }
        )

    def delete_delivery_stream(self):
        stream_name = self.parameters["DeliveryStreamName"]
        self.kinesis_backend.delete_delivery_stream(stream_name)
        return json.dumps({})

    def firehose_put_record(self):
        stream_name = self.parameters["DeliveryStreamName"]
        record_data = self.parameters["Record"]["Data"]

        record = self.kinesis_backend.put_firehose_record(stream_name, record_data)
        return json.dumps({"RecordId": record.record_id})

    def put_record_batch(self):
        stream_name = self.parameters["DeliveryStreamName"]
        records = self.parameters["Records"]

        request_responses = []
        for record in records:
            record_response = self.kinesis_backend.put_firehose_record(
                stream_name, record["Data"]
            )
            request_responses.append({"RecordId": record_response.record_id})
        return json.dumps({"FailedPutCount": 0, "RequestResponses": request_responses})

    def add_tags_to_stream(self):
        stream_name = self.parameters.get("StreamName")
        tags = self.parameters.get("Tags")
        self.kinesis_backend.add_tags_to_stream(stream_name, tags)
        return json.dumps({})

    def list_tags_for_stream(self):
        stream_name = self.parameters.get("StreamName")
        exclusive_start_tag_key = self.parameters.get("ExclusiveStartTagKey")
        limit = self.parameters.get("Limit")
        response = self.kinesis_backend.list_tags_for_stream(
            stream_name, exclusive_start_tag_key, limit
        )
        return json.dumps(response)

    def remove_tags_from_stream(self):
        stream_name = self.parameters.get("StreamName")
        tag_keys = self.parameters.get("TagKeys")
        self.kinesis_backend.remove_tags_from_stream(stream_name, tag_keys)
        return json.dumps({})
