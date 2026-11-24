/*
 * CaramOS: Show desktop, a thin strip at the very end of the Xfce taskbar, as on Windows and in Linux Mint.
 *
 * Copyright (C) 2026 Vietnam Linux Family <developer@vietnamlinuxfamily.net>
 *
 * This program is free software; you can redistribute it and/or modify it under the terms of the GNU General
 * Public License as published by the Free Software Foundation; either version 2 of the License, or (at your
 * option) any later version.
 *
 * Xfce's own Show Desktop plugin is a square button as wide as the panel is high. On CaramOS it would push the right
 * island away from the edge of the screen, or come before Feedback & Help, which ends the island. This one is a strip
 * STRIP_WIDTH pixels wide, the whole height of the panel, after the island (tickets H-1189 and H-1192). It shows
 * nothing until the pointer is on it; the theme then draws a thin line (#caramos-show-desktop in caramos-ota's
 * panel-islands.css). A click hides every window, a second one brings them back, as Super+D does: it asks the window
 * manager through _NET_SHOWING_DESKTOP (EWMH), as Xfce's plugin does through libwnck.
 */

#include <locale.h>
#include <string.h>

#include <gtk/gtk.h>
#include <gdk/gdkx.h>
#include <X11/Xlib.h>
#include <X11/Xatom.h>
#include <libxfce4panel/libxfce4panel.h>

#define STRIP_WIDTH 4

static gboolean
showing_desktop (GdkScreen *screen)
{
  Display       *display = GDK_SCREEN_XDISPLAY (screen);
  Window         root = GDK_WINDOW_XID (gdk_screen_get_root_window (screen));
  Atom           actual_type;
  int            actual_format;
  unsigned long  items, after;
  unsigned char *data = NULL;
  gboolean       showing = FALSE;

  gdk_x11_display_error_trap_push (gdk_screen_get_display (screen));
  if (XGetWindowProperty (display, root, XInternAtom (display, "_NET_SHOWING_DESKTOP", False), 0, 1, False,
                          XA_CARDINAL, &actual_type, &actual_format, &items, &after, &data) == Success
      && data != NULL && actual_type == XA_CARDINAL && actual_format == 32 && items == 1)
    showing = *(long *) data != 0;
  if (data != NULL)
    XFree (data);
  gdk_x11_display_error_trap_pop_ignored (gdk_screen_get_display (screen));
  return showing;
}

static void
toggle_desktop (GtkButton *button,
                gpointer   data)
{
  GdkScreen *screen = gtk_widget_get_screen (GTK_WIDGET (button));
  Display   *display = GDK_SCREEN_XDISPLAY (screen);
  Window     root = GDK_WINDOW_XID (gdk_screen_get_root_window (screen));
  XEvent     event;

  memset (&event, 0, sizeof (event));
  event.xclient.type = ClientMessage;
  event.xclient.window = root;
  event.xclient.message_type = XInternAtom (display, "_NET_SHOWING_DESKTOP", False);
  event.xclient.format = 32;
  event.xclient.data.l[0] = showing_desktop (screen) ? 0 : 1;
  XSendEvent (display, root, False, SubstructureRedirectMask | SubstructureNotifyMask, &event);
  XFlush (display);
}

static gboolean
size_changed (XfcePanelPlugin *plugin,
              gint             size)
{
  /* The whole height of a horizontal panel, so the corner of the screen shows the desktop too. */
  if (xfce_panel_plugin_get_orientation (plugin) == GTK_ORIENTATION_HORIZONTAL)
    gtk_widget_set_size_request (GTK_WIDGET (plugin), STRIP_WIDTH, size);
  else
    gtk_widget_set_size_request (GTK_WIDGET (plugin), size, STRIP_WIDTH);
  return TRUE;
}

static const gchar *
tooltip (void)
{
  const gchar *language = g_getenv ("LANGUAGE");
  const gchar *messages = setlocale (LC_MESSAGES, NULL);

  /* CaramOS speaks English and Vietnamese; this one string needs no catalogue of its own. */
  if ((language != NULL && *language != '\0') ? g_str_has_prefix (language, "vi")
                                              : (messages != NULL && g_str_has_prefix (messages, "vi")))
    return "Hiện màn hình nền";
  return "Show desktop";
}

static void
construct (XfcePanelPlugin *plugin)
{
  GtkWidget *strip = gtk_button_new ();

  gtk_widget_set_name (strip, "caramos-show-desktop");
  gtk_button_set_relief (GTK_BUTTON (strip), GTK_RELIEF_NONE);
  gtk_widget_set_can_focus (strip, FALSE);
  gtk_widget_set_tooltip_text (strip, tooltip ());
  atk_object_set_name (gtk_widget_get_accessible (strip), tooltip ());
  g_signal_connect (strip, "clicked", G_CALLBACK (toggle_desktop), NULL);
  g_signal_connect (plugin, "size-changed", G_CALLBACK (size_changed), NULL);

  xfce_panel_plugin_set_small (plugin, FALSE);
  gtk_container_add (GTK_CONTAINER (plugin), strip);
  xfce_panel_plugin_add_action_widget (plugin, strip);
  gtk_widget_show_all (GTK_WIDGET (plugin));
  size_changed (plugin, xfce_panel_plugin_get_size (plugin));
}

XFCE_PANEL_PLUGIN_REGISTER (construct);
