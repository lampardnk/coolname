<?php
/**
 * PHP LFI Chain — legacy file viewer.
 *
 * The page loader uses include() with user input.
 * "Sanitization" rejects purely alphanumeric names but lets stream wrappers through —
 * the developer thought non-alphanumeric paths couldn't be useful.
 *
 * Flag 1 (/flag1.txt)  — path traversal:  ?page=../../../flag1.txt
 * Flag 2 (config.php)  — PHP filter:       ?page=php://filter/convert.base64-encode/resource=pages/config.php
 * Flag 3 (/flag3.txt)  — command injection via admin panel (password in config.php source)
 */
?>
<!DOCTYPE html>
<html>
<head><title>LegacyCMS</title>
<style>
  body{font-family:monospace;background:#1b1b2f;color:#c8c8e0;margin:0;padding:0}
  header{background:#e43f5a;padding:16px 32px}
  header h1{margin:0;color:#fff;font-size:1.3rem}
  nav{background:#162447;padding:8px 32px}
  nav a{color:#1f4068;color:#6ec6f5;margin-right:16px;text-decoration:none}
  main{max-width:900px;margin:32px auto;padding:0 20px}
  .card{background:#162447;border:1px solid #1f4068;border-radius:6px;padding:20px;margin:16px 0}
  pre{background:#0d1b2a;padding:12px;border-radius:4px;white-space:pre-wrap;word-break:break-all;color:#a8d8ea}
  a{color:#6ec6f5}footer{text-align:center;padding:20px;color:#555;font-size:0.8rem}
</style>
</head>
<body>
<header><h1>📄 LegacyCMS</h1></header>
<nav>
  <a href="/">Home</a>
  <a href="/?page=about">About</a>
  <a href="/?page=contact">Contact</a>
  <a href="/admin.php">Admin</a>
</nav>
<main>

<?php
$page = isset($_GET['page']) ? $_GET['page'] : 'home';

/*
 * "Security" check:
 * If the page name is purely alphanumeric, load from pages/ directory.
 * Otherwise (special chars like ../ or php://) — use the path as-is.
 * The developer believed non-alphanumeric paths were "unusual enough to be safe."
 */
if (preg_match('/^[a-zA-Z0-9_-]+$/', $page)) {
    $file = __DIR__ . '/pages/' . $page . '.php';
    if (file_exists($file)) {
        include($file);
    } else {
        echo '<div class="card"><p>Page not found: <code>' . htmlspecialchars($page) . '</code></p></div>';
    }
} else {
    // VULNERABLE: attacker-controlled include() with no further validation
    @include($page);
}
?>

</main>
<footer>LegacyCMS v0.3 &mdash; "Security through obscurity since 2009"</footer>
</body>
</html>
