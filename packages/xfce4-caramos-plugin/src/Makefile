# Builds the panel plugins. Used by debian/rules (make -C src, make -C src install DESTDIR=...).
PKG_CONFIG ?= pkg-config
PACKAGES := libxfce4panel-2.0 gtk+-3.0 x11
PLUGINS := caramos-control-center caramos-show-desktop
MULTIARCH ?= $(shell dpkg-architecture -qDEB_HOST_MULTIARCH 2>/dev/null || $(CC) -print-multiarch)
PLUGINDIR := /usr/lib/$(MULTIARCH)/xfce4/panel/plugins
DESKTOPDIR := /usr/share/xfce4/panel/plugins

CFLAGS ?= -O2 -g
override CFLAGS += -Wall -Wextra -Wno-unused-parameter -fPIC $(shell $(PKG_CONFIG) --cflags $(PACKAGES))
override LDLIBS += $(shell $(PKG_CONFIG) --libs $(PACKAGES))

all: $(PLUGINS:%=lib%.so)

lib%.so: %.c
	$(CC) $(CPPFLAGS) $(CFLAGS) -shared -o $@ $< $(LDFLAGS) $(LDLIBS)

install: all
	for plugin in $(PLUGINS); do \
	  install -D -m644 lib$$plugin.so $(DESTDIR)$(PLUGINDIR)/lib$$plugin.so && \
	  install -D -m644 $$plugin.desktop $(DESTDIR)$(DESKTOPDIR)/$$plugin.desktop || exit 1; \
	done

clean:
	rm -f $(PLUGINS:%=lib%.so)

.PHONY: all install clean
