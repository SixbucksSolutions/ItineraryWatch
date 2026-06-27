DROP TABLE IF EXISTS monitored_urls;

CREATE TABLE monitored_urls (
    url_id                      UUID                            PRIMARY KEY DEFAULT uuidv7(),

    -- The UNIQUE constraint automatically creates a B-tree index that planner can use for search
    url                         VARCHAR                         UNIQUE NOT NULL,

    last_scrape_timestamp       TIMESTAMP WITH TIME ZONE,

    -- Enforces that the UUID *must* be version 7
    CONSTRAINT enforce_uuid_v7
        CHECK (uuid_extract_version(url_id) = 7)
);

-- speeds up searches for rows that need a re-scrape due to last scrape >= 24 hours
--      IMPORTANT NOTE: index only used if "last_scrape-timestamp" is "naked" on its
--                      side of comparison operator.
--                      Do NOW() - INTERVAL '24 hours' on OTHER side of >= or <=
CREATE INDEX idx_monitored_urls_last_scrape_timestamp ON monitored_urls(last_scrape_timestamp);
