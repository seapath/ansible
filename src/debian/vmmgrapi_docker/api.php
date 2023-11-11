<?php
if ((isset($_GET["cmd"])) and (isset($_GET["code"]))) {
  $code = htmlspecialchars($_GET["code"]);
  $cmd = htmlspecialchars($_GET["cmd"]);
  if (is_string($cmd) and is_string($code)) {
    if (preg_match("#^vm-mgr [a-zA-Z0-9 \-_/]+$#", $cmd)) {
      $pipe = "/run/vmmgr.pipe";
      system("echo \"$code$cmd\" >$pipe",$retval);
      $fpipe=fopen($pipe,'r');
      $output=fread($fpipe,10000);
      fclose($fpipe);
      echo "$output";
    }
  }
}
?>
