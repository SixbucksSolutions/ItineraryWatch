import json
import logging
import time
import uuid

import boto3
import aws_lambda_powertools.utilities.data_classes
import aws_lambda_powertools.utilities.typing

import psycopg

_logger: aws_lambda_powertools.Logger = aws_lambda_powertools.Logger(service="scraper_launcher")
_logger.setLevel(logging.INFO)

_ssm_client = boto3.client("ssm", region_name="us-east-2")
_sns_client = boto3.client("sns", region_name="us-east-2")

@_logger.inject_lambda_context(log_event=True)
@aws_lambda_powertools.utilities.data_classes.event_source(
    data_class=aws_lambda_powertools.utilities.data_classes.EventBridgeEvent)
def lambda_entry_point_event_bridge(_event: aws_lambda_powertools.utilities.data_classes.EventBridgeEvent,
                                    _context: aws_lambda_powertools.utilities.typing.LambdaContext | None) -> None:

    _logger.debug("Starting periodic scraper launcher")

    # Read Postgres connection details from Parameter Store
    postgres_connection_params: dict[str, str] = _get_pg_server_connection_details()
    # _logger.debug(f"Postgres connection params: {json.dumps(postgres_connection_params, indent=4)}")

    # Get the SNS topic we're using as the scraper function's trigger from Param Store
    sns_topic_arn: str = _ssm_client.get_parameter(Name="/itinerary_watch/sns/arn_scraper_trigger")['Parameter']['Value']
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
            _logger.debug("Starting query for URL's ready to be scraped")
            start_time: float = time.perf_counter()
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT      url_id, url
                    FROM        monitored_urls
                    WHERE       last_scrape_timestamp <= NOW() - INTERVAL '24 hours'
                                OR last_scrape_timestamp IS NULL;
                    """
                )
                end_time = time.perf_counter()

                _logger.info(
                    f"DB query for URL's to scrape completed successfully in {end_time - start_time:.03f} seconds")

                for url_id, url in cur:
                    _send_sns_trigger_to_scraper(sns_topic_arn, url_id, url)

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


def _send_sns_trigger_to_scraper(sns_topic_arn: str, url_id: uuid.UUID, url: str) -> None:
    sns_message_payload: str = json.dumps(
        {
            "schema_datetime"   : "2026-06-24 15:00+00:00",
            "monitored_url_id"  : str(url_id),
            "monitored_url"     : url,
        }
    )
    try:
        _sns_client.publish(
            TopicArn    = sns_topic_arn,
            Message     = sns_message_payload,
        )
    except Exception as e:
        _logger.error(f"SNS publish failed: {e}")
        raise

    _logger.info(f"Sent scraper trigger for URL ID {str(url_id)}")
