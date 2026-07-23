import json
import logging
import typing
import uuid
import aws_lambda_powertools.utilities.data_classes
import aws_lambda_powertools.utilities.typing
import botocore.exceptions
import boto3
import psycopg


_logger: aws_lambda_powertools.Logger = aws_lambda_powertools.Logger(service="customer_notifier")
_logger.setLevel(logging.INFO)

_ssm_client = boto3.client("ssm",   region_name="us-east-2")
_ses_client = boto3.client("ses",   region_name="us-east-2")


@_logger.inject_lambda_context(log_event=True)
@aws_lambda_powertools.utilities.data_classes.event_source(
    data_class=aws_lambda_powertools.utilities.data_classes.SNSEvent)
def lambda_entry_point_sns(event: aws_lambda_powertools.utilities.data_classes.SNSEvent,
                           _context: aws_lambda_powertools.utilities.typing.LambdaContext | None) -> None:

    # _logger.debug(json.dumps(event, indent=4, sort_keys=True))

    # 1. Loop through the list of records
    for record in event.records:
        _process_sns_event_record(record)


def _process_sns_event_record(
        curr_record: aws_lambda_powertools.utilities.data_classes.sns_event.SNSEventRecord) -> None:

    curr_sns_message_id: uuid.UUID = uuid.UUID(curr_record.sns.message_id)
    _logger.info(f"Starting to process new SNS message with ID {str(curr_sns_message_id)}")

    try:
        parsed_payload: dict[str, str | list[str]] = json.loads(curr_record.sns.message)
    except Exception as e:
        _logger.warning(f"Could not parse JSON from SNS message payload, error: {e}")
        return

    _logger.debug(f"Got scrape start message: {json.dumps(parsed_payload, indent=4, sort_keys=True)}")

    # Make sure it's a valid message
    if not _valid_json(parsed_payload):
        _logger.warning(f"Got invalid JSON, aborting: {json.dumps(parsed_payload, indent=4, sort_keys=True)}")
        return

    user_id: uuid.UUID = uuid.UUID(str(parsed_payload["user_id"]))
    changed_url_ids: list[uuid.UUID] = [uuid.UUID(str(url_id)) for url_id in parsed_payload["changed_url_ids"]]

    _logger.info(f"SNS message ID {str(curr_sns_message_id)} contains changes for user ID {str(user_id)}")

    _notify_customer(user_id, changed_url_ids)


def _valid_json(parsed_payload: dict[str, str | list[str]]) -> bool:

    # Needs to be a dict with proper keys and values

    if not isinstance(parsed_payload, dict):
        _logger.warning("Parsed JSON was not a dict")
        return False

    if not len(parsed_payload) == 3:
        _logger.warning("Dict did not have exactly three keys")
        return False

    check_keys: list[str] = ["schema_datetime", "user_id", "changed_url_ids"]
    if not all(key in parsed_payload for key in check_keys):
        _logger.warning(f"Dict did not contain all of the expected keys: {sorted(check_keys)}")
        return False

    if not isinstance(parsed_payload["schema_datetime"], str):
        _logger.warning("Schema version value not a string")
        return False

    supported_schema_datetimes: set[str] = {
        "2026-06-30 15:00+00:00",
    }
    if parsed_payload["schema_datetime"] not in supported_schema_datetimes:
        _logger.warning("Unsupported schema version")
        return False

    if not isinstance(parsed_payload["user_id"], str):
        _logger.warning("monitored_url value not a string")
        return False

    try:
        if uuid.UUID(str(parsed_payload["user_id"])).version != 7:
            _logger.warning("user_id was a UUID but not UUID v7")
            return False
    except ValueError as e:
        _logger.warning("user_id was not a UUID")
        return False

    # Check changed UUIDs
    if not isinstance(parsed_payload["changed_url_ids"], list):
        _logger.warning("changedUrl_ids not a list")
        return False

    for candidate_url_id in parsed_payload["changed_url_ids"]:
        if not isinstance(candidate_url_id, str):
            _logger.warning("candidate url list value not a string")
            return False

        try:
            if uuid.UUID(str(candidate_url_id)).version != 7:
                _logger.warning("url ID value was a UUID but not UUID v7")
                return False
        except ValueError as e:
            _logger.warning("url ID value was not a UUID")
            return False

    return True


def _notify_customer(user_id: uuid.UUID, changed_url_ids: list[uuid.UUID]) -> None:
    _logger.info(f"Sending email notification to user ID {str(user_id)}")

    # Read Postgres connection details from Parameter Store
    postgres_connection_params: dict[str, str] = _get_pg_server_connection_details()
    # _logger.debug(f"Postgres connection params: {json.dumps(postgres_connection_params, indent=4)}")

    # raise NotImplementedError("Not a thing yet")

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

            # Launch a transaction as we're logically chaining queries; need all to succeed or none
            with conn.transaction():

                # Context managers for cursors ensure they *also* close automatically
                with conn.cursor() as cur:
                    # pull details on the user searches
                    cur.execute(
                        """
                        SELECT      user_search_id, search_name
                        FROM        user_searches
                        WHERE       user_id = %s
                                    AND watched_url = ANY(%s)
                        ORDER BY    search_name;
                        """,

                        (user_id, changed_url_ids)
                    )

                    retrieved_rows: list[tuple[str, str]] = cur.fetchall()

                    if len(retrieved_rows) != len(changed_url_ids):
                        _logger.warning(f"Search for watched URL's didn't get all data")
                        raise RuntimeError(f"Searched for URL's {changed_url_ids} but didn't get all rows")

                    _logger.debug("Got proper number of rows back")

                    # _logger.debug(json.dumps(retrieved_rows, indent=4, default=str))

                    if not _send_customer_notification(user_id, email_address, retrieved_rows):
                        _logger.info("email sent time not updated as email was not sent successfully")
                        return

                    # Email was sent; update DB so we don't spam user
                    _update_db_last_email_time(cur, user_id)

    except Exception as e:
        _logger.critical(f"Database error: {e}")
        raise


def _read_parameter_store_param(parameter_name: str) -> str:
    return _ssm_client.get_parameter(Name=parameter_name)['Parameter']['Value']


def _read_parameter_store_params(parameter_names: list[str]) -> dict[str, str]:
    retrieved_params: list[dict] = _ssm_client.get_parameters(Names=parameter_names)['Parameters']
    # _logger.debug(f"Retrieved params: {retrieved_params}")
    return_dict: dict[str, str] = {}
    for param_idx, param_details in enumerate(retrieved_params):
        return_dict[param_details['Name']] = retrieved_params[param_idx]['Value']
    return return_dict


def _update_db_last_email_time(db_cursor, user_id: uuid.UUID) -> None:
    db_cursor.execute(
        """
        UPDATE  users 
        SET     user_last_emailed = NOW()
        WHERE   user_id = %s;
        """,

        (user_id, )
    )

    _logger.info(f"Updated last email time for user {str(user_id)} in DB")


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


def _send_customer_notification(
        user_id: uuid.UUID, email_address: str, retrieved_rows: list[tuple[str, str]]) -> bool:

    email_contents: dict[str, typing.Any] = {
        "customer_id"                   : user_id,
        "email_address"                 : email_address,
        "updated_itinerary_searches"    : [],
    }

    for curr_row in retrieved_rows:
        email_contents["updated_itinerary_searches"].append(
            {
                "customer_search_id"    : curr_row[0],
                "customer_search_name"  : curr_row[1],
            }
        )

    # _logger.debug(f"TODO call SES with {json.dumps(email_contents, default=str)}")

    try:
        response = _ses_client.send_email(
            Source="notify@itinerarywatch.sixbuckssolutions.com",
            Destination={
                "ToAddresses": [email_contents["email_address"]],
            },
            Message={
                "Subject": {
                    "Data"          : "ItineraryWatch User Search Update Notification",
                    "Charset"       : "UTF-8",
                },
                "Body": {
                    "Text": {
                        "Data"      : "This is a test email sent using boto3.",
                        "Charset"   : "UTF-8",
                    }
                }
            }
        )
        _logger.info(f"Email sent! Message ID: {response["MessageId"]}")
    except botocore.exceptions.ClientError as e:
        _logger.warning(f"Error sending email: {e.response["Error"]["Message"]}")
        return False

    return True
