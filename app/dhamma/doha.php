<?php
/**
 * Morning doha player — intended to run at 06:37 via cron.
 * Force test: GONG_FORCE_DOHA=1 php /home/dhamma/doha.php
 */
require_once dirname(__FILE__) . "/constants.inc";

$doha = array(
    0 => 0,
    1 => "D01_0632_Doha-Hindi-1_NA_NA.mp3",
    2 => "D02_0632_Doha-Hindi-2_NA_NA.mp3",
    3 => "D03_0632_Doha-Rajasthani-1_NA_NA.mp3",
    4 => "D04_0632_Doha-Rajasthani-2_NA_NA.mp3",
    5 => "D05_0632_Doha-Anicca-_NA_NA.mp3",
    6 => "D06_0632_Doha-Samatha-_NA_NA.mp3",
    7 => "D07_0632_Doha-JoDhareSoPaya-1_NA_NA.mp3",
    8 => "D08_0632_Doha-JoDhareSoPaya-2_NA_NA.mp3",
    9 => "D09_0632_Doha-Hindi-1_NA_NA.mp3",
    10 => "D10_0632_Doha-Awakening-Inspiring_NA_NA.mp3",
    11 => "D11_0632_Doha-Homage_NA_NA.mp3",
);

db_connect();

$q = "SELECT * FROM settings LEFT JOIN course_types ON course_type = ct_id";
$handle = mysqli_query($DB_CONN, $q);
$row = mysqli_fetch_array($handle);
if (!$row) {
    logit("No settings row");
    exit(1);
}

$enabled = (int)$row["enabled"];
$doha_enabled = (int)$row["doha_enabled"];

if (!$enabled) {
    logit("Cron Disabled, exiting");
    exit(1);
}
if (!$doha_enabled) {
    logit("Doha disabled, exiting");
    exit(0);
}

$force = (getenv("GONG_FORCE_DOHA") === "1");
// Cron runs at 06:37; require hour 06 unless forced
if (!$force && (int)date("H") !== 6) {
    exit(0);
}

$zero_day = $row["zero_day"];
$total_days = (int)$row["ct_days"];
$doha_vol = (int)$row["doha_vol"];
$vol_pct = doha_volume_percent($doha_vol);
$course_name = $row["ct_name"];
$anapana_total = (int)$row["ct_anapana_days"];
$relay_enabled = !empty($row["relay"]);

$current_date = time();
$zero_date = strtotime($zero_day);
$datediff = $current_date - $zero_date;
$current_day = (int)floor($datediff / (60 * 60 * 24));

mysqli_close($DB_CONN);

function pick_doha_index($current_day, $total_days, $anapana_total)
{
    if ($current_day <= $anapana_total) {
        $a = (($current_day - 1) % 3) + 1;
    } elseif ($current_day == ($anapana_total + 1)) {
        $a = 4;
    } else {
        $a = 3 + (($current_day - ($anapana_total + 1)) % 6) + 1;
    }

    $metta_days = ($total_days >= 30) ? 2 : 1;
    if ($current_day == $total_days) {
        $a = 11;
    } elseif ($current_day >= ($total_days - $metta_days)) {
        $a = 10;
    }
    return $a;
}

function play_doha_file($filename, $vol_pct, $relay_enabled, $label)
{
    if ($relay_enabled) {
        relay_on();
        sleep(5);
    }
    logit($label);
    kill_players();
    play_mp3($filename, $vol_pct);
    logit("Finished playing Doha");
    if ($relay_enabled) {
        relay_off();
    }
}

if ($current_day > 0 && $current_day <= $total_days) {
    $a = pick_doha_index($current_day, $total_days, $anapana_total);
    $filename = $DOHA_DIR . $doha[$a];
    play_doha_file(
        $filename,
        $vol_pct,
        $relay_enabled,
        "$course_name course, Day $current_day, Playing Doha - $filename"
    );
} else {
    $a = rand(1, 11);
    $filename = $DOHA_DIR . $doha[$a];
    play_doha_file(
        $filename,
        $vol_pct,
        $relay_enabled,
        "No Course, Playing Doha - $filename"
    );
}
