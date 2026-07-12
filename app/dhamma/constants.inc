<?php
/**
 * DhammaGong shared config and helpers.
 * Optional override file (written by installer): /etc/gongserver/config.inc.php
 */

$GONG_HOME = "/home/dhamma";
$DB_HOST = "localhost";
$DB_USER = "gong";
$DB_PASS = "changeme";
$DB_NAME = "gong";
$GONG_FILE = $GONG_HOME . "/gong-replaceme.mp3";
$DOHA_DIR = $GONG_HOME . "/doha/";
$RELAY_BIN = $GONG_HOME . "/relay-control";
$LOG_FILE = "/var/log/gong.log";
// Player: mpg123 (preferred), mpv, or omxplayer (legacy Buster)
$AUDIO_PLAYER = "mpg123";

if (is_readable("/etc/gongserver/config.inc.php")) {
    require_once "/etc/gongserver/config.inc.php";
}

function logit($msg)
{
    global $LOG_FILE;
    $data = date("[Y-m-d H:i:s] ") . $msg . "\n";
    $fp = @fopen($LOG_FILE, "a");
    if ($fp) {
        fwrite($fp, $data);
        fclose($fp);
    }
}

function db_connect()
{
    global $DB_HOST, $DB_USER, $DB_PASS, $DB_NAME, $DB_CONN;
    $DB_CONN = @mysqli_connect($DB_HOST, $DB_USER, $DB_PASS);
    if (!$DB_CONN) {
        logit("Could not connect to mysql server: " . mysqli_connect_error());
        exit(1);
    }
    if (!mysqli_select_db($DB_CONN, $DB_NAME)) {
        logit("Could not select DB: " . mysqli_error($DB_CONN));
        exit(1);
    }
    mysqli_set_charset($DB_CONN, "utf8mb4");
}

function check_zero_day()
{
    global $DB_CONN;
    $today = date("Y-m-d");
    $q = "SELECT * FROM courses WHERE c_date >= ? ORDER BY c_date LIMIT 1";
    $stmt = mysqli_prepare($DB_CONN, $q);
    if (!$stmt) {
        return;
    }
    mysqli_stmt_bind_param($stmt, "s", $today);
    mysqli_stmt_execute($stmt);
    $handle = mysqli_stmt_get_result($stmt);
    $row = $handle ? mysqli_fetch_array($handle) : null;
    mysqli_stmt_close($stmt);
    if (!$row) {
        return;
    }
    $zero_day = $row["c_date"];
    $course_type = (int)$row["c_type"];
    if ($zero_day == $today) {
        $u = "UPDATE settings SET zero_day = ?, course_type = ?";
        $st = mysqli_prepare($DB_CONN, $u);
        mysqli_stmt_bind_param($st, "si", $today, $course_type);
        mysqli_stmt_execute($st);
        mysqli_stmt_close($st);
    }
}

function show_log()
{
    global $LOG_FILE;
    $cmd = "tail -n 50 " . escapeshellarg($LOG_FILE) . " 2>/dev/null";
    $out = array();
    exec($cmd, $out);
    $out = implode("<br>", array_reverse($out));
    echo $out;
}

/** Stop any known audio player instances used by this app. */
function kill_players()
{
    // intentional broad stop so gong/doha never stack
    exec("pkill -x mpg123 2>/dev/null");
    exec("pkill -x mpv 2>/dev/null");
    exec("pkill -x omxplayer 2>/dev/null");
    exec("pkill -x omxplayer.bin 2>/dev/null");
}

/**
 * Map UI doha_vol 0..9 to a player volume.
 * 0 quietest, 9 loudest.
 */
function doha_volume_percent($doha_vol)
{
    $v = (int)$doha_vol;
    if ($v < 0) {
        $v = 0;
    }
    if ($v > 9) {
        $v = 9;
    }
    // 30% .. 100%
    return 30 + (int)round(($v / 9.0) * 70);
}

/**
 * Play one MP3 file, blocking until done.
 * $volume_percent 0-100 for players that support it.
 */
function play_mp3($filename, $volume_percent = 90)
{
    global $AUDIO_PLAYER;
    $filename = (string)$filename;
    if (!is_readable($filename)) {
        logit("Audio file not readable: $filename");
        return false;
    }
    $vol = (int)$volume_percent;
    if ($vol < 0) {
        $vol = 0;
    }
    if ($vol > 100) {
        $vol = 100;
    }

    $file_q = escapeshellarg($filename);

    // Best-effort ALSA PCM boost (may fail on some devices — ignore)
    @exec("amixer sset PCM,0 {$vol}% 2>/dev/null");
    @exec("amixer sset Master {$vol}% 2>/dev/null");
    @exec("amixer sset Headphone {$vol}% 2>/dev/null");

    if ($AUDIO_PLAYER === "omxplayer" && is_executable("/usr/bin/omxplayer")) {
        // legacy: volume via '-' keypresses (original behaviour)
        $count = (int)round((100 - $vol) / 10);
        $descriptors = array(
            0 => array("pipe", "r"),
            1 => array("pipe", "w"),
            2 => array("pipe", "w"),
        );
        $process = proc_open("/usr/bin/omxplayer --no-keys --no-osd $file_q", $descriptors, $pipes);
        if (!is_resource($process)) {
            logit("Could not execute omxplayer - $filename");
            return false;
        }
        sleep(1);
        for ($i = 0; $i < $count; $i++) {
            @fwrite($pipes[0], "-");
            sleep(1);
        }
        @fclose($pipes[0]);
        @fclose($pipes[1]);
        @fclose($pipes[2]);
        proc_close($process);
        return true;
    }

    if ($AUDIO_PLAYER === "mpv" && (is_executable("/usr/bin/mpv") || is_executable("/usr/local/bin/mpv"))) {
        $mpv = is_executable("/usr/bin/mpv") ? "/usr/bin/mpv" : "/usr/local/bin/mpv";
        $cmd = sprintf(
            "%s --really-quiet --no-video --volume=%d %s",
            escapeshellcmd($mpv),
            $vol,
            $file_q
        );
        exec($cmd);
        return true;
    }

    // default: mpg123
    $mpg = is_executable("/usr/bin/mpg123") ? "/usr/bin/mpg123" : "mpg123";
    // Dummy/test mode: decode only (Docker/CI without ALSA, or GONG_AUDIO_DUMMY=1)
    $dummy = (getenv("GONG_AUDIO_DUMMY") === "1")
        || $AUDIO_PLAYER === "dummy"
        || $AUDIO_PLAYER === "test";
    if ($dummy) {
        $cmd = sprintf("%s -q -t %s", escapeshellcmd($mpg), $file_q);
        exec($cmd);
        return true;
    }
    // Use -q quiet; volume mostly via amixer above.
    $cmd = sprintf("%s -q %s", escapeshellcmd($mpg), $file_q);
    exec($cmd);
    return true;
}

function relay_on()
{
    global $RELAY_BIN;
    if (is_executable($RELAY_BIN)) {
        exec(escapeshellarg($RELAY_BIN) . " on");
    }
}

function relay_off()
{
    global $RELAY_BIN;
    if (is_executable($RELAY_BIN)) {
        exec(escapeshellarg($RELAY_BIN) . " off");
    }
}
