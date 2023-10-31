FROM httpd:2.4-alpine

# Set up working directory
WORKDIR /usr/local/apache2

# Update Apache configuration to use SSL and set up document root
RUN { \
  echo 'LoadModule ssl_module modules/mod_ssl.so'; \
  echo 'Listen 443'; \
  echo '<VirtualHost *:443>'; \
  echo '  DocumentRoot "/www"'; \
  echo '  SSLEngine on'; \
  echo '  SSLCertificateFile "/certs/cert.pem"'; \
  echo '  SSLCertificateKeyFile "/certs/priv.key"'; \
  echo '</VirtualHost>'; \
  } >> conf/httpd.conf

# Make sure the directories are available and set proper permissions
RUN mkdir -p /www /downloads /certs \
  && chmod -R 755 /www /downloads /certs

# Installiere curl
RUN apk --no-cache add curl

# Copy the run script and set permissions
COPY run_endpoint.sh .
RUN chmod +x run_endpoint.sh

# Expose the necessary ports
EXPOSE 443

# Set the entry point to the run script
ENTRYPOINT ["./run_endpoint.sh"]
