import json
import logging
import time
import uuid

import boto3
import aws_lambda_powertools.utilities.data_classes
import aws_lambda_powertools.utilities.typing

import psycopg

_logger: aws_lambda_powertools.Logger = aws_lambda_powertools.Logger(service="itinerary_change_detection")
_logger.setLevel(logging.INFO)

_ssm_client = boto3.client("ssm", region_name="us-east-2")
_sns_client = boto3.client("sns", region_name="us-east-2")


@_logger.inject_lambda_context(log_event=True)
@aws_lambda_powertools.utilities.data_classes.event_source(
    data_class=aws_lambda_powertools.utilities.data_classes.EventBridgeEvent)
def lambda_entry_point_event_bridge(_event: aws_lambda_powertools.utilities.data_classes.EventBridgeEvent,
                                    _context: aws_lambda_powertools.utilities.typing.LambdaContext | None) -> None:

    _logger.debug("Starting itinerary change detection")

    # Read Postgres connection details from Parameter Store
    postgres_connection_params: dict[str, str] = _get_pg_server_connection_details()
    # _logger.debug(f"Postgres connection params: {json.dumps(postgres_connection_params, indent=4)}")

    # Get the SNS topic we're using as the scraper function's trigger from Param Store
    sns_topic_arn: str = _ssm_client.get_parameter(Name="/itinerary_watch/sns/arn_user_notifier")['Parameter']['Value']
    _logger.debug(f"SNS topic ARN: {sns_topic_arn}")

    try:

        # Context manager syntax ("with") gets the connection auto-closed at scope exit
        with psycopg.connect(
                    host=postgres_connection_params["db_hostname"],
                    dbname=postgres_connection_params["db_dbname"],
                    user=postgres_connection_params["db_user"],
                    password=postgres_connection_params["db_password"],
                    sslmode="verify-full",
                    sslrootcert="src/aws-rds-global-bundle.pem",
                ) as conn:

            # Context managers for cursors ensure they *also* close automatically
            _logger.debug("Starting query for users with searches that have been updated")
            start_time: float = time.perf_counter()

            urls_per_user: dict[uuid.UUID, list[uuid.UUID]] = {}
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT user_searches.user_id, user_searches.watched_url
                    FROM users
                    JOIN user_searches
                    ON users.user_id = user_searches.user_id
                    JOIN monitored_urls
                    ON user_searches.watched_url = monitored_urls.url_id
                    WHERE monitored_urls.contents_changed_timestamp > users.user_last_emailed
                        OR (monitored_urls.contents_changed_timestamp IS NOT NULL AND users.user_last_emailed IS NULL);
                    """
                )
                end_time = time.perf_counter()

                _logger.info(
                    f"DB query for users to notify completed successfully in {end_time - start_time:.03f} seconds")

                for user_id, url_id in cur:
                    if user_id not in urls_per_user:
                        urls_per_user[user_id] = []
                    urls_per_user[user_id].append(url_id)

            # Send one notification per user with all their changed URL's
            for user_id in sorted(urls_per_user):
                _send_sns_trigger_to_notifier(sns_topic_arn, user_id, sorted(urls_per_user[user_id]))

    except Exception as e:
        _logger.critical(f"Database error: {e}")
        raise


def _get_pg_server_connection_details() -> dict[str, str]:
    db_params_keys: list[str] = [
        "/itinerary_watch/postgres/db_hostname",
        "/itinerary_watch/postgres/db_dbname",
        "/itinerary_watch/postgres/db_user",
        "/itinerary_watch/postgres/db_password",
    ]

    returned_params: dict[str, str] = _read_parameter_store_params(db_params_keys)

    return_dict: dict[str, str] = {}
    for curr_key in db_params_keys:
        # shorten to final token
        return_dict[curr_key.split("/")[-1]] = returned_params[curr_key]

    return return_dict


def _read_parameter_store_params(parameter_names: list[str]) -> dict[str, str]:
    retrieved_params: list[dict] = _ssm_client.get_parameters(Names=parameter_names)['Parameters']
    # _logger.debug(f"Retrieved params: {retrieved_params}")
    return_dict: dict[str, str] = {}
    for param_idx, param_details in enumerate(retrieved_params):
        return_dict[param_details['Name']] = retrieved_params[param_idx]['Value']
    return return_dict


def _send_sns_trigger_to_notifier(sns_topic_arn: str, user_id: uuid.UUID, url_id_list: list[uuid.UUID]) -> None:
    sns_message_payload: str = json.dumps(
        {
            "schema_datetime"   : "2026-06-30 15:00+00:00",
            "user_id"           : user_id,
            "changed_url_ids"   : url_id_list,
        },

        default=str
    )
    try:
        _sns_client.publish(
            TopicArn    = sns_topic_arn,
            Message     = sns_message_payload,
        )
    except Exception as e:
        _logger.error(f"SNS publish failed: {e}")
        raise

    _logger.info(f"Sent notifier trigger for user ID {str(user_id)} with one or more updated monitored searches")
