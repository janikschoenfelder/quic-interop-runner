#!/bin/sh

# Setze die notwendige Routing-Konfiguration
/setup.sh

# Warte darauf, dass der Simulator startet
/wait-for-it.sh sim:57832 -s -t 30

if [ "$ROLE" = "client" ]; then
    echo "Client-Modus aktiviert"
    
    # Wechsle in das Download-Verzeichnis
    cd /downloads || exit 1
    
    # Download der Datei vom Server
    curl -O http://193.167.100.100
    
    echo "Download abgeschlossen"
    
    elif [ "$ROLE" = "server" ]; then
    
    echo "Server-Modus aktiviert"
    
    # Wechsle in das www-Verzeichnis
    cd /usr/local/apache2/htdocs || exit 1
    
    # Starte den Apache Server
    httpd -DFOREGROUND
else
    echo "Unbekannte Rolle: $ROLE"
    exit 1
fi
