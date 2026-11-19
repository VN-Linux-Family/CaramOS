# Builds the panel plugin. Used by debian/rules (make -C src, make -C src install DESTDIR=...).
PKG_CONFIG ?= pkg-config
PACKAGES := libxfce4panel-2.0 gtk+-3.0
MULTIARCH ?= $(shell dpkg-architecture -qDEB_HOST_MULTIARCH 2>/dev/null || $(CC) -print-multiarch)
PLUGINDIR := /usr/lib/$(MULTIARCH)/xfce4/panel/plugins
DESKTOPDIR := /usr/share/xfce4/panel/plugins

CFLAGS ?= -O2 -g
override CFLAGS += -Wall -Wextra -Wno-unused-parameter -fPIC $(shell $(PKG_CONFIG) --cflags $(PACKAGES))
override LDLIBS += $(shell $(PKG_CONFIG) --libs $(PACKAGES))

all: libcaramos-control-center.so

libcaramos-control-center.so: caramos-control-center.c
	$(CC) $(CPPFLAGS) $(CFLAGS) -shared -o $@ $< $(LDFLAGS) $(LDLIBS)

install: all
	install -D -m644 libcaramos-control-center.so $(DESTDIR)$(PLUGINDIR)/libcaramos-control-center.so
	install -D -m644 caramos-control-center.desktop $(DESTDIR)$(DESKTOPDIR)/caramos-control-center.desktop

clean:
	rm -f libcaramos-control-center.so

.PHONY: all install clean
