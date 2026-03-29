FROM php:8.2-apache

# Enable mod_rewrite for .htaccess support
RUN a2enmod rewrite

# Place flags outside web root (inaccessible via direct HTTP)
RUN echo 'CTF{lfi_path_traversal_reads_files}' > /flag1.txt && \
    echo 'CTF{rce_via_command_injection_admin}' > /flag3.txt && \
    chmod 644 /flag1.txt /flag3.txt

# Copy web application
COPY . /var/www/html/

# Allow .htaccess overrides for pages/ subdirectory
RUN printf '<Directory /var/www/html/pages>\n\
    AllowOverride All\n\
    Require all granted\n\
</Directory>\n' > /etc/apache2/conf-available/pages-access.conf && \
    a2enconf pages-access

# Ensure shell_exec is not disabled (it isn't by default in php:apache images)
RUN php -r "if (!function_exists('shell_exec')) { exit(1); }" && echo "shell_exec available"

EXPOSE 80
