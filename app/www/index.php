<?php
/**
 * DhammaGong admin UI — designed for a private centre Wi‑Fi AP.
 * Still unauthenticated by design (match original); protect the network.
 */
require_once "/home/dhamma/constants.inc";

db_connect();
$message = "";
$zdate = "";

if (isset($_REQUEST["del"]) && is_numeric($_REQUEST["del"])) {
    $id = (int)$_REQUEST["del"];
    $st = mysqli_prepare($DB_CONN, "DELETE FROM courses WHERE c_id = ?");
    mysqli_stmt_bind_param($st, "i", $id);
    mysqli_stmt_execute($st);
    mysqli_stmt_close($st);
    check_zero_day();
    header("Location: index.php");
    exit;
}

if (isset($_POST["enablesubmit"]) && $_POST["enablesubmit"] === "Enable Cron") {
    mysqli_query($DB_CONN, "UPDATE settings SET enabled = 1");
    header("Location: index.php");
    exit;
}
if (isset($_POST["disablesubmit"]) && $_POST["disablesubmit"] === "Disable Cron") {
    mysqli_query($DB_CONN, "UPDATE settings SET enabled = 0");
    header("Location: index.php");
    exit;
}

if (isset($_POST["settingssubmit"]) && $_POST["settingssubmit"] === "Save Settings") {
    $doha_enabled = (int)($_POST["doha_enabled"] ?? 0) ? 1 : 0;
    $gong_enabled = (int)($_POST["gong_enabled"] ?? 0) ? 1 : 0;
    $relay_enabled = (int)($_POST["relay_enabled"] ?? 0) ? 1 : 0;
    $gong_track = ($_POST["gong_track"] ?? "ting") === "drum" ? "drum" : "ting";
    $doha_vol = (int)($_POST["doha_vol"] ?? 6);
    if ($doha_vol < 0) {
        $doha_vol = 0;
    }
    if ($doha_vol > 9) {
        $doha_vol = 9;
    }
    $st = mysqli_prepare(
        $DB_CONN,
        "UPDATE settings SET doha_enabled=?, gong_enabled=?, relay=?, gong_track=?, doha_vol=?"
    );
    mysqli_stmt_bind_param($st, "iiisi", $doha_enabled, $gong_enabled, $relay_enabled, $gong_track, $doha_vol);
    mysqli_stmt_execute($st);
    mysqli_stmt_close($st);
    header("Location: index.php");
    exit;
}

if (isset($_POST["datesubmit"]) && $_POST["datesubmit"] === "Set Date") {
    $set_date = $_POST["s_date"] ?? "";
    if ($set_date !== "" && preg_match("/^[0-9]{4}-(0[1-9]|1[0-2])-(0[1-9]|[1-2][0-9]|3[0-1]) [0-9]{2}:[0-9]{2}$/", $set_date)) {
        // only allow safe characters already validated by regex
        shell_exec('sudo /bin/date -s ' . escapeshellarg($set_date));
        shell_exec("sudo /sbin/hwclock -w 2>/dev/null");
        check_zero_day();
        $message = "Date Set Successfully";
    } else {
        $message = "Invalid Date";
    }
}

if (isset($_POST["coursesubmit"]) && $_POST["coursesubmit"] === "Add course") {
    $c_date = $_POST["c_date"] ?? "";
    $c_type = (int)($_POST["c_type"] ?? 0);
    if ($c_date !== "" && preg_match("/^[0-9]{4}-(0[1-9]|1[0-2])-(0[1-9]|[1-2][0-9]|3[0-1])$/", $c_date) && $c_type > 0) {
        $st = mysqli_prepare($DB_CONN, "INSERT INTO courses (c_date, c_type) VALUES (?, ?)");
        mysqli_stmt_bind_param($st, "si", $c_date, $c_type);
        mysqli_stmt_execute($st);
        mysqli_stmt_close($st);
        check_zero_day();
        $message = "Course added successfully";
    } else {
        $message = "Date Invalid";
    }
}

if (isset($_POST["zdatesubmit"]) && $_POST["zdatesubmit"] === "Set Zero Date") {
    $z_date = $_POST["z_date"] ?? "";
    $c_type = (int)($_POST["c_type"] ?? 0);
    if ($z_date !== "" && preg_match("/^[0-9]{4}-(0[1-9]|1[0-2])-(0[1-9]|[1-2][0-9]|3[0-1])$/", $z_date) && $c_type > 0) {
        $st = mysqli_prepare($DB_CONN, "UPDATE settings SET zero_day=?, course_type=?");
        mysqli_stmt_bind_param($st, "si", $z_date, $c_type);
        mysqli_stmt_execute($st);
        mysqli_stmt_close($st);
        $message = "Zero date set successfully";
    } else {
        $message = "Date Invalid";
    }
}

$courses_table = "";
$hand = mysqli_query(
    $DB_CONN,
    'SELECT c_id, DATE_FORMAT(c_date, "%Y-%m-%d (%a, %D %b %Y)") AS d, ct_name
     FROM courses LEFT JOIN course_types ON c_type = ct_id
     WHERE c_date >= DATE_SUB(CURDATE(), INTERVAL 2 MONTH)
     ORDER BY c_date'
);
while ($row = mysqli_fetch_array($hand)) {
    $courses_table .= "<tr>";
    $courses_table .= "<td>" . htmlspecialchars($row["d"]) . "</td>";
    $courses_table .= "<td>" . htmlspecialchars($row["ct_name"]) . "</td>";
    $courses_table .= '<td><a href="index.php?del=' . (int)$row["c_id"] . '" class="del">Del</a></td>';
    $courses_table .= "</tr>";
}

$ctypes = "";
$hand = mysqli_query($DB_CONN, "SELECT * FROM course_types ORDER BY ct_id");
while ($row = mysqli_fetch_array($hand)) {
    $ctypes .= '<option value="' . (int)$row["ct_id"] . '">' . htmlspecialchars($row["ct_name"]) . "</option>";
}

$hand = mysqli_query(
    $DB_CONN,
    "SELECT enabled, doha_enabled, gong_enabled, gong_track, relay, doha_vol, zero_day, course_type FROM settings LIMIT 1"
);
$e_r = mysqli_fetch_array($hand);
$enabled = (int)$e_r["enabled"];
$doha_enabled = (int)$e_r["doha_enabled"];
$gong_enabled = (int)$e_r["gong_enabled"];
$relay_enabled = (int)$e_r["relay"];
$gong_track = $e_r["gong_track"];
$doha_vol = (int)$e_r["doha_vol"];
$zdate = $e_r["zero_day"];
$active_type = (int)$e_r["course_type"];
$date = date("Y-m-d H:i");

// Rebuild ctypes with selected active type for zero-date form
$ctypes_zero = "";
$hand = mysqli_query($DB_CONN, "SELECT * FROM course_types ORDER BY ct_id");
while ($row = mysqli_fetch_array($hand)) {
    $sel = ((int)$row["ct_id"] === $active_type) ? " selected" : "";
    $ctypes_zero .= '<option value="' . (int)$row["ct_id"] . '"' . $sel . ">" . htmlspecialchars($row["ct_name"]) . "</option>";
}

mysqli_close($DB_CONN);
?>
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>DhammaGong</title>
  <style>
    body { font-family: system-ui, sans-serif; margin: 1.5rem; max-width: 52rem; }
    h1 { font-size: 1.25rem; }
    h2 { font-size: 1.05rem; margin-top: 1.25rem; }
    table { border-collapse: collapse; width: 100%; }
    th, td { border: 1px solid #ccc; padding: 0.4rem 0.6rem; text-align: left; }
    .msg { color: #0645ad; }
    .status-on { color: #0a0; font-weight: 600; }
    .status-off { color: #a00; font-weight: 600; }
  </style>
  <script>
    function lala() {
      var x = document.getElementsByClassName("del");
      for (var i = 0; i < x.length; i++) {
        x[i].addEventListener("click", function (event) {
          if (!confirm("Are you sure you want to delete?")) {
            event.preventDefault();
          }
        });
      }
    }
  </script>
</head>
<body onload="lala()">
  <h1>
    DhammaGong —
    <?php echo htmlspecialchars($date); ?>
    (
    <?php if ($enabled): ?>
      <span class="status-on">Cron Enabled</span>
    <?php else: ?>
      <span class="status-off">Cron DISABLED</span>
    <?php endif; ?>
    )
  </h1>

  <form method="post" action="index.php" style="display:inline">
    <?php if (!$enabled): ?>
      <input type="submit" name="enablesubmit" value="Enable Cron">
    <?php else: ?>
      <input type="submit" name="disablesubmit" value="Disable Cron">
    <?php endif; ?>
  </form>

  <?php if ($message !== ""): ?>
    <p class="msg"><?php echo htmlspecialchars($message); ?></p>
  <?php endif; ?>

  <form name="sdate" action="index.php" method="post">
    <h2>
      Doha:
      Enabled <input type="radio" name="doha_enabled" value="1" <?php if ($doha_enabled) echo "checked"; ?>>
      Disabled <input type="radio" name="doha_enabled" value="0" <?php if (!$doha_enabled) echo "checked"; ?>>
    </h2>
    <h2>
      Doha Volume (0 to 9):
      <input type="number" name="doha_vol" min="0" max="9" value="<?php echo (int)$doha_vol; ?>">
    </h2>
    <h2>
      Gong:
      Enabled <input type="radio" name="gong_enabled" value="1" <?php if ($gong_enabled) echo "checked"; ?>>
      Disabled <input type="radio" name="gong_enabled" value="0" <?php if (!$gong_enabled) echo "checked"; ?>>
    </h2>
    <h2>
      Gong Track:
      Ting <input type="radio" name="gong_track" value="ting" <?php if ($gong_track === "ting") echo "checked"; ?>>
      Drum <input type="radio" name="gong_track" value="drum" <?php if ($gong_track === "drum") echo "checked"; ?>>
    </h2>
    <h2>
      Amplifier:
      Enabled <input type="radio" name="relay_enabled" value="1" <?php if ($relay_enabled) echo "checked"; ?>>
      Disabled <input type="radio" name="relay_enabled" value="0" <?php if (!$relay_enabled) echo "checked"; ?>>
    </h2>
    <input type="submit" name="settingssubmit" value="Save Settings">

    <h2>Set Date/Time</h2>
    <input type="text" name="s_date" value="<?php echo htmlspecialchars($date); ?>" size="30">
    (YYYY-mm-dd hh:mm)
    <input type="submit" name="datesubmit" value="Set Date">
  </form>

  <form name="zdate" action="index.php" method="post">
    <h2>Set Zero Date</h2>
    <input type="text" name="z_date" value="<?php echo htmlspecialchars($zdate); ?>" size="30">
    (YYYY-mm-dd)
    Course Type: <select name="c_type"><?php echo $ctypes_zero; ?></select>
    <input type="submit" name="zdatesubmit" value="Set Zero Date">
  </form>

  <h2>Courses</h2>
  <form name="cdate" action="index.php" method="post">
    Course Date: <input type="text" name="c_date" value=""> (YYYY-mm-dd)
    Course Type: <select name="c_type"><?php echo $ctypes; ?></select>
    <input type="submit" name="coursesubmit" value="Add course">
  </form>
  <table>
    <thead>
      <tr><th>Course Date</th><th>Course Type</th><th>Delete</th></tr>
    </thead>
    <tbody>
      <?php echo $courses_table; ?>
    </tbody>
  </table>

  <h2>Log Entries</h2>
  <?php show_log(); ?>
</body>
</html>
