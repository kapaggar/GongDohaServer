<?php
// Docker test overrides (mounted into container)
$DB_HOST = getenv("GONG_DB_HOST") ?: "db";
$DB_USER = getenv("GONG_DB_USER") ?: "gong";
$DB_PASS = getenv("GONG_DB_PASS") ?: "gongpass";
$DB_NAME = getenv("GONG_DB_NAME") ?: "gong";
$GONG_HOME = "/home/dhamma";
$GONG_FILE = $GONG_HOME . "/gong-replaceme.mp3";
$DOHA_DIR = $GONG_HOME . "/doha/";
$RELAY_BIN = $GONG_HOME . "/relay-control";
$LOG_FILE = "/var/log/gong.log";
$AUDIO_PLAYER = getenv("GONG_AUDIO_PLAYER") ?: "dummy";
// Ensure dummy flag is visible even if only config is loaded
if (getenv("GONG_AUDIO_DUMMY") === false || getenv("GONG_AUDIO_DUMMY") === "") {
    putenv("GONG_AUDIO_DUMMY=1");
}
