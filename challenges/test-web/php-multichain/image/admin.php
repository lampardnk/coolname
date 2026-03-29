<?php
/**
 * Admin diagnostic panel.
 * Password protected — find the password by reading config.php source via LFI.
 * The command parameter is passed directly to shell_exec() — command injection.
 *
 * Exploit:
 *   1. Read config.php via: /?page=php://filter/convert.base64-encode/resource=pages/config.php
 *   2. base64-decode the output → find ADMIN_PASS and FLAG2
 *   3. Visit /admin.php?pass=<ADMIN_PASS>&cmd=cat+/flag3.txt
 */
require_once(__DIR__ . '/pages/config.php');

$pass = isset($_GET['pass']) ? $_GET['pass'] : '';
$cmd  = isset($_GET['cmd'])  ? $_GET['cmd']  : 'id';

$authed = ($pass === ADMIN_PASS);
$output = '';
if ($authed) {
    // INTENTIONALLY VULNERABLE — unsanitized shell_exec
    $output = shell_exec($cmd . ' 2>&1');
}
?>
<!DOCTYPE html>
<html>
<head><title>Admin — LegacyCMS</title>
<style>
  body{font-family:monospace;background:#1b1b2f;color:#c8c8e0;padding:32px}
  h1{color:#e43f5a}
  input{background:#0d1b2a;border:1px solid #1f4068;color:#c8c8e0;padding:8px;border-radius:4px;width:300px;margin:4px 0 12px}
  button{background:#e43f5a;color:#fff;border:none;padding:8px 20px;border-radius:4px;cursor:pointer}
  pre{background:#0d1b2a;border:1px solid #1f4068;padding:16px;border-radius:4px;white-space:pre-wrap;word-break:break-all;min-height:60px}
  .warn{color:#f0a500;background:#1f1400;border:1px solid #f0a500;padding:12px;border-radius:4px}
</style>
</head>
<body>
<h1>🔧 Admin Diagnostic Panel</h1>

<?php if (!$authed): ?>
<form method="GET">
  <input type="hidden" name="cmd" value="<?= htmlspecialchars($cmd) ?>">
  <label>Admin Password:</label><br>
  <input type="password" name="pass" placeholder="enter password">
  <button>Authenticate</button>
</form>
<?php if ($pass !== ''): ?>
<p style="color:#e43f5a">Wrong password.</p>
<?php endif; ?>

<?php else: ?>
<form method="GET">
  <input type="hidden" name="pass" value="<?= htmlspecialchars($pass) ?>">
  <label>Run command:</label><br>
  <input type="text" name="cmd" value="<?= htmlspecialchars($cmd) ?>">
  <button>Execute</button>
</form>
<h2>Output</h2>
<pre><?= htmlspecialchars($output ?? '(no output)') ?></pre>
<?php endif; ?>

</body></html>
