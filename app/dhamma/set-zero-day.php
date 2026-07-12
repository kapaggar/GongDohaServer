<?php
require_once dirname(__FILE__) . "/constants.inc";
db_connect();
check_zero_day();
mysqli_close($DB_CONN);
