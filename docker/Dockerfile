FROM php:8.2-apache-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends \
      libmariadb-dev \
      mpg123 \
      alsa-utils \
      cron \
      sudo \
    && docker-php-ext-install mysqli \
    && a2enmod rewrite \
    && rm -rf /var/lib/apt/lists/*

# App paths expected by code
RUN mkdir -p /home/dhamma /etc/gongserver /var/log \
    && touch /var/log/gong.log \
    && chmod 666 /var/log/gong.log \
    && echo 'www-data ALL=(ALL) NOPASSWD: /bin/date -s *, /sbin/hwclock -w, /usr/sbin/hwclock -w' \
         > /etc/sudoers.d/020_www-data-gong \
    && chmod 440 /etc/sudoers.d/020_www-data-gong

# Quiet ServerName warning
RUN echo 'ServerName gongserver-local' > /etc/apache2/conf-available/servername.conf \
    && a2enconf servername

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
CMD ["apache2-foreground"]
