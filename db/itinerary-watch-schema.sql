DROP TABLE IF EXISTS user_searches;
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


CREATE TABLE user_searches (
    user_search_id              UUID            PRIMARY KEY     DEFAULT uuidv7(),
    user_id                     UUID            NOT NULL,
    watched_url                 UUID            NOT NULL        REFERENCES monitored_urls(url_id),
    search_name                 VARCHAR         NOT NULL,

    -- Prevents duplicate searches for the same URL by the same user
    CONSTRAINT unique_user_watched_url UNIQUE (user_id, watched_url),

    -- Search names are unique per USER
    CONSTRAINT unique_user_search_name UNIQUE (user_id, search_name),

    -- Enforces that UUID *must* be version 7
    CONSTRAINT enforce_uuid_v7 CHECK (
        uuid_extract_version(user_search_id) = 7
        AND
        uuid_extract_version(user_id) = 7
    )
);

CREATE INDEX idx_user_searches_user_id      ON user_searches(user_id);
CREATE INDEX idx_user_searches_watched_url  ON user_searches(watched_url);