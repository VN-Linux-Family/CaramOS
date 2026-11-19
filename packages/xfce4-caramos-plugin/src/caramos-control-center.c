/*
 * CaramOS Control Center button for the Xfce panel.
 *
 * Copyright (C) 2026 Vietnam Linux Family <developer@vietnamlinuxfamily.net>
 *
 * This program is free software; you can redistribute it and/or modify it under the terms of the GNU General
 * Public License as published by the Free Software Foundation; either version 2 of the License, or (at your
 * option) any later version.
 *
 * The Control Center itself is written in Python and ships with caramos-ota
 * (/usr/share/caramos-ota/xfce/caramos-control-center). This plugin only gives it its place in the taskbar: an
 * XEmbed socket, into which it starts the Control Center with --plug <socket id>. The Control Center draws its
 * button there and opens its popup from it. If the Control Center stops while it is embedded, it is started again.
 */

#include <signal.h>
#include <sys/types.h>

#include <gtk/gtk.h>
#include <gtk/gtkx.h>
#include <libxfce4panel/libxfce4panel.h>

#define CONTROL_CENTER "/usr/share/caramos-ota/xfce/caramos-control-center"
#define RESTART_SECONDS 3

typedef struct
{
  XfcePanelPlugin *plugin;
  GtkWidget       *socket;
  GPid             pid;
  guint            child_watch_id;
  guint            restart_id;
} CaramosPlugin;

static void start_control_center (CaramosPlugin *cc);

static gboolean
restart_control_center (gpointer data)
{
  CaramosPlugin *cc = data;

  cc->restart_id = 0;
  start_control_center (cc);
  return G_SOURCE_REMOVE;
}

static void
schedule_restart (CaramosPlugin *cc)
{
  if (cc->restart_id == 0)
    cc->restart_id = g_timeout_add_seconds (RESTART_SECONDS, restart_control_center, cc);
}

static void
control_center_exited (GPid     pid,
                       gint     status,
                       gpointer data)
{
  CaramosPlugin *cc = data;

  g_spawn_close_pid (pid);
  cc->pid = 0;
  cc->child_watch_id = 0;

  /* A Control Center that was already running took over the socket, and this process only handed it the socket
   * id: nothing to do while the button is there. */
  if (gtk_socket_get_plug_window (GTK_SOCKET (cc->socket)) == NULL)
    schedule_restart (cc);
}

static void
start_control_center (CaramosPlugin *cc)
{
  gchar   *socket_id;
  gchar   *argv[4];
  GError  *error = NULL;

  if (cc->pid != 0 || !gtk_widget_get_realized (cc->socket))
    return;

  socket_id = g_strdup_printf ("%lu", (gulong) gtk_socket_get_id (GTK_SOCKET (cc->socket)));
  argv[0] = (gchar *) CONTROL_CENTER;
  argv[1] = (gchar *) "--plug";
  argv[2] = socket_id;
  argv[3] = NULL;

  if (g_spawn_async (NULL, argv, NULL, G_SPAWN_DO_NOT_REAP_CHILD, NULL, NULL, &cc->pid, &error))
    {
      cc->child_watch_id = g_child_watch_add (cc->pid, control_center_exited, cc);
    }
  else
    {
      g_warning ("could not start %s: %s", CONTROL_CENTER, error->message);
      g_error_free (error);
      schedule_restart (cc);
    }

  g_free (socket_id);
}

static gboolean
plug_removed (GtkSocket     *socket,
              CaramosPlugin *cc)
{
  /* The Control Center went away: keep the socket and start it again. */
  if (cc->pid == 0)
    schedule_restart (cc);
  return TRUE;
}

static void
free_data (XfcePanelPlugin *plugin,
           CaramosPlugin   *cc)
{
  if (cc->restart_id != 0)
    g_source_remove (cc->restart_id);
  if (cc->child_watch_id != 0)
    g_source_remove (cc->child_watch_id);
  if (cc->pid != 0)
    {
      kill (cc->pid, SIGTERM);
      g_spawn_close_pid (cc->pid);
    }
  g_free (cc);
}

static void
construct (XfcePanelPlugin *plugin)
{
  CaramosPlugin *cc = g_new0 (CaramosPlugin, 1);

  cc->plugin = plugin;
  cc->socket = gtk_socket_new ();

  /* The panel constructs a plugin when it is realized, so the socket is realized as soon as it is added: connect
   * first, and start the Control Center at once if the socket is already there. */
  g_signal_connect_swapped (cc->socket, "realize", G_CALLBACK (start_control_center), cc);
  g_signal_connect (cc->socket, "plug-removed", G_CALLBACK (plug_removed), cc);
  g_signal_connect (plugin, "free-data", G_CALLBACK (free_data), cc);

  gtk_container_add (GTK_CONTAINER (plugin), cc->socket);
  gtk_widget_show_all (GTK_WIDGET (plugin));
  if (gtk_widget_get_realized (cc->socket))
    start_control_center (cc);
}

XFCE_PANEL_PLUGIN_REGISTER (construct);
