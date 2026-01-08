# -*- coding: utf-8 -*-
# DMG ayarları - dmgbuild için

import os

application = "dist/AutoCut.app"
appname = os.path.basename(application)

# Volume icon - uses the app icon
badge_icon = "resources/icon.icns"

# Volume ayarları
volume_name = "AutoCut 0.1.0"
format = "UDBZ"  # Sıkıştırılmış

# Pencere ayarları
size = (640, 480)
background = None

# İkon pozisyonları
icon_size = 128
icon_locations = {
    appname: (140, 240),
    "Applications": (500, 240),
}

# Applications symlink
symlinks = {"Applications": "/Applications"}
