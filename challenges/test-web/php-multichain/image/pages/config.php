<?php
/**
 * Application configuration.
 *
 * Flag 2 is here — readable only via PHP filter source disclosure:
 *   /?page=php://filter/convert.base64-encode/resource=pages/config.php
 *
 * Direct HTTP access to pages/ is blocked by .htaccess.
 * Including this file executes it — all you see is nothing (defines constants).
 * To READ the source, you need the filter wrapper.
 */

define('ADMIN_PASS', 'L3g4cyCMS!');
define('FLAG2', 'CTF{php_filter_reveals_source_code}');

// DB settings (unused in this demo)
define('DB_HOST', 'localhost');
define('DB_USER', 'cms');
define('DB_PASS', 'cms_db_password');
define('DB_NAME', 'legacycms');
