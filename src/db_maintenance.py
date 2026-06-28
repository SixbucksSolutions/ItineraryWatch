import logging
import time

import boto3
import aws_lambda_powertools.utilities.data_classes
import aws_lambda_powertools.utilities.typing

import psycopg

_logger: logging.Logger = logging.getLogger()
_logger.setLevel(logging.DEBUG)

_ssm_client = boto3.client("ssm", region_name="us-east-2")


@aws_lambda_powertools.utilities.data_classes.event_source(
    data_class=aws_lambda_powertools.utilities.data_classes.EventBridgeEvent)
def lambda_entry_point_event_bridge(_event: aws_lambda_powertools.utilities.data_classes.EventBridgeEvent,
                                    _context: aws_lambda_powertools.utilities.typing.LambdaContext | None) -> None:

    _logger.debug("Starting DB maintenance")

    # Read Postgres connection details from Parameter Store
    postgres_connection_params: dict[str, str] = _get_pg_server_connection_details()
    # _logger.debug(f"Postgres connection params: {json.dumps(postgres_connection_params, indent=4)}")

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

            # need to turn autocommit on so command is not run in a transaction block
            conn.autocommit = True

            # Context managers for cursors ensure they *also* close automatically
            start_time: float = time.perf_counter()
            with conn.cursor() as cur:
                cur.execute("VACUUM ANALYZE;")
            end_time = time.perf_counter()

            _logger.info(f"DB maintenance completed successfully in {end_time - start_time:.03f} seconds")
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


if __name__ == "__main__":
    logging.basicConfig()
    raw_event = {
        "version": "0",
        "id": "12345678-1234-1234-1234-123456789012",
        "detail-type": "MyCustomDetailType",
        "source": "my.custom.source",
        "account": "123456789012",
        "time": "2026-06-28T12:00:00Z",
        "region": "us-east-1",
        "resources": [],
        "detail": {
            "status": "success",
            "message": "Test payload processed"
        }
    }

    lambda_entry_point_event_bridge(
        aws_lambda_powertools.utilities.data_classes.EventBridgeEvent(raw_event), None)
