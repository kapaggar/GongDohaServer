<?php
/**
 * Gong scheduler — intended to run every minute via cron.
 */
require_once dirname(__FILE__) . "/constants.inc";

db_connect();

$q = "SELECT * FROM settings LEFT JOIN course_types ON course_type = ct_id";
$handle = mysqli_query($DB_CONN, $q);
$row = mysqli_fetch_array($handle);
if (!$row) {
    logit("No settings row");
    exit(1);
}

$enabled = (int)$row["enabled"];
$gong_enabled = (int)$row["gong_enabled"];
$gong_track = $row["gong_track"];
$GONG_FILE = str_replace("replaceme", $gong_track, $GONG_FILE);

if (!$enabled) {
    logit("Cron Disabled, exiting");
    exit(1);
}
if (!$gong_enabled) {
    // silent exit — no log spam every minute
    exit(0);
}

$zero_day = $row["zero_day"];
$total_days = (int)$row["ct_days"];
$repeat_delay = (int)$row["repeat_delay"];
if ($repeat_delay < 0) {
    $repeat_delay = 0;
}
$relay_enabled = !empty($row["relay"]);

$current_date = time();
$zero_date = strtotime($zero_day);
$datediff = $current_date - $zero_date;
$current_day = (int)floor($datediff / (60 * 60 * 24));
$current_time = date("Gi");
$course_type = (int)$row["course_type"];
$course_name = $row["ct_name"];

if ($current_day >= 0 && $current_day <= $total_days) {
    $q = "SELECT COUNT(id) AS a FROM schedule WHERE type = ? AND day_no = ?";
    $st = mysqli_prepare($DB_CONN, $q);
    mysqli_stmt_bind_param($st, "ii", $course_type, $current_day);
    mysqli_stmt_execute($st);
    $hand = mysqli_stmt_get_result($st);
    $available = mysqli_fetch_array($hand);
    mysqli_stmt_close($st);
    $day_no = ($available && (int)$available["a"] > 0) ? $current_day : 2;

    $q = "SELECT * FROM schedule WHERE type = ? AND day_no = ? AND start_time = ?";
    $st = mysqli_prepare($DB_CONN, $q);
    $stime = (int)$current_time;
    mysqli_stmt_bind_param($st, "iii", $course_type, $day_no, $stime);
    mysqli_stmt_execute($st);
    $hand = mysqli_stmt_get_result($st);
} else {
    $course_name = "No";
    $current_day = -1;
    $q = "SELECT * FROM schedule WHERE day_no = -1 AND start_time = ?";
    $st = mysqli_prepare($DB_CONN, $q);
    $stime = (int)$current_time;
    mysqli_stmt_bind_param($st, "i", $stime);
    mysqli_stmt_execute($st);
    $hand = mysqli_stmt_get_result($st);
}

if ($hand && mysqli_num_rows($hand) > 0) {
    $srow = mysqli_fetch_array($hand);
    $repeat = (int)$srow["total_repeat"];
    logit("$course_name course, Day $current_day, Playing $GONG_FILE $repeat times");
    if ($relay_enabled) {
        relay_on();
        sleep(5);
    }
    for ($i = 1; $i <= $repeat; $i++) {
        kill_players();
        play_mp3($GONG_FILE, 90);
        if ($i < $repeat && $repeat_delay > 0) {
            sleep($repeat_delay);
        }
    }
    if ($relay_enabled) {
        relay_off();
    }
}

if (isset($st) && $st) {
    mysqli_stmt_close($st);
}
mysqli_close($DB_CONN);
