"""CaramOS Control Center for the Xfce edition.

The Cinnamon edition has the Control Center applet (usr/share/caramos-ota/applets/caramos-control-center@caramos), which
only runs inside Cinnamon. This is the same Control Center for Xfce, written with GTK: the same tiles, texts
(gettext domain caramos-control-center), accent colours (net.vietnamlinuxfamily.caramos.control-center) and system
services (NetworkManager, BlueZ, UPower, power-profiles-daemon), with Xfce's own tools where the two desktops differ.

It runs inside the taskbar's right island: the CaramOS panel plugin (packages/xfce4-caramos-plugin) starts
`caramos-control-center --plug <socket>` and shows its panel button; a click opens the popup.
"""
