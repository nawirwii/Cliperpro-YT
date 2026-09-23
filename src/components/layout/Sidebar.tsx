import { useEffect, useState } from "react";
import { NavLink } from "react-router-dom";
import {
  PlusCircle,
  FolderOpen,
  Bot,
  Settings,
  PanelLeftClose,
  PanelLeftOpen,
  Sun,
  Moon,
  Clapperboard,
} from "lucide-react";
import { useAppStore } from "@/stores/appStore";
import { cn } from "@/lib/utils";
import { APP_VERSION } from "@/config/version";
import { menuIcon } from "@/config/menuIcons";
import { DEFAULT_MENU_ITEMS, fetchMenu, readCachedMenu, type MenuItem } from "@/hooks/menu";
import { AdvertiseDialog } from "@/components/AdvertiseDialog";
import { open as openUrl } from "@tauri-apps/plugin-shell";

const navItems = [
  { to: "/", icon: PlusCircle, label: "Create" },
  { to: "/library", icon: FolderOpen, label: "Library" },
  { to: "/processing-clips", icon: Clapperboard, label: "Processing" },
  { to: "/ai-models", icon: Bot, label: "AI Models" },
  { to: "/settings", icon: Settings, label: "Settings" },
];

export function Sidebar() {
  const { sidebarCollapsed, toggleSidebar, availableUpdate, theme, setTheme } = useAppStore();
  const [showAdvertise, setShowAdvertise] = useState(false);

  // Render from cache (or the built-in defaults) on the first paint, then
  // refresh in the background. The sidebar never waits on the network.
  const [menuItems, setMenuItems] = useState<MenuItem[]>(
    () => readCachedMenu() ?? DEFAULT_MENU_ITEMS
  );

  useEffect(() => {
    let cancelled = false;
    fetchMenu().then((items) => {
      if (!cancelled && items) setMenuItems(items);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  const linkClass = cn(
    "flex items-center gap-3 px-3 py-2.5 rounded-[var(--radius-sm)] text-sm font-medium transition-all duration-200 cursor-pointer",
    "text-[var(--color-text-secondary)] hover:bg-[var(--color-bg-hover)] hover:text-[var(--color-text-primary)]",
    sidebarCollapsed && "justify-center px-0"
  );

  return (
    <aside
      className={cn(
        "flex flex-col h-screen w-56 bg-[var(--color-bg-sidebar)] border-r border-[var(--color-border-light)] transition-all duration-300 ease-in-out shrink-0",
        sidebarCollapsed && "w-14"
      )}
    >
      {/* App brand */}
      <div className={cn("px-4 py-4 border-b border-[var(--color-border-light)]", sidebarCollapsed && "px-0 flex justify-center")}>
        <div className="flex items-center gap-2">
          <div className="w-7 h-7 rounded-[var(--radius-sm)] bg-[var(--color-accent)] flex items-center justify-center shrink-0">
            <Clapperboard className="w-4 h-4 text-[var(--color-text-on-accent)]" />
          </div>
          {!sidebarCollapsed && (
            <span className="text-sm font-semibold text-[var(--color-text-primary)] whitespace-nowrap">
              YT Short Clipper
            </span>
          )}
        </div>
      </div>

      {/* Nav items */}
      <nav className={cn("flex flex-col gap-1 p-2 flex-1 overflow-y-auto", sidebarCollapsed && "items-center")}>
        {navItems.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.to === "/"}
            className={({ isActive }) =>
              cn(
                "flex items-center gap-3 px-3 py-2.5 rounded-[var(--radius-sm)] text-sm font-medium transition-all duration-200 w-full",
                isActive
                  ? "bg-[var(--color-accent)] text-[var(--color-text-on-accent)] shadow-sm"
                  : "text-[var(--color-text-secondary)] hover:bg-[var(--color-bg-hover)] hover:text-[var(--color-text-primary)]",
                sidebarCollapsed && "justify-center px-0 w-auto"
              )
            }
            title={item.label}
          >
            <item.icon className="w-4 h-4 shrink-0" />
            {!sidebarCollapsed && <span className="truncate">{item.label}</span>}
          </NavLink>
        ))}

        {/* External links, served by the menu API */}
        {menuItems.length > 0 && (
          <div className="my-2 border-t border-[var(--color-border-light)]" />
        )}

        {menuItems.map((item) => {
          const Icon = menuIcon(item.icon);
          return (
            <button
              key={item.id}
              onClick={() => openUrl(item.url).catch(console.error)}
              className={cn(linkClass, "w-full", sidebarCollapsed && "w-auto")}
              title={item.label}
            >
              <Icon className="w-4 h-4 shrink-0" />
              {!sidebarCollapsed && <span className="truncate">{item.label}</span>}
            </button>
          );
        })}
      </nav>

      {/* Advertise + theme + version + collapse toggle */}
      <div className="p-3 border-t border-[var(--color-border-light)]">
        {!sidebarCollapsed && (
          <>
            <button
              onClick={() => setShowAdvertise(true)}
              className="w-full mb-2 text-[10px] leading-tight text-[var(--color-text-muted)] hover:text-[var(--color-accent)] hover:underline transition-colors cursor-pointer text-center"
            >
              Want your link here?
            </button>

            <div className="mb-2 text-center">
              <p className="text-[10px] text-[var(--color-text-muted)]">
                v{APP_VERSION}
              </p>
              {availableUpdate && (
                <button
                  onClick={() => openUrl(availableUpdate.download_url)}
                  className="text-[10px] text-[var(--color-accent)] hover:underline mt-0.5"
                >
                  Update: v{availableUpdate.version}
                </button>
              )}
            </div>
          </>
        )}

        <div className={cn("flex items-center gap-1", sidebarCollapsed ? "flex-col" : "justify-between")}>
          {/* Theme toggle */}
          <button
            onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
            className={cn(
              "flex items-center gap-2 px-2 py-1.5 rounded-[var(--radius-sm)] text-[var(--color-text-muted)] hover:bg-[var(--color-bg-hover)] hover:text-[var(--color-text-secondary)] transition-all duration-200 cursor-pointer",
              sidebarCollapsed && "px-0 justify-center"
            )}
            title={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
          >
            {theme === "dark" ? (
              <Sun className="w-4 h-4" />
            ) : (
              <Moon className="w-4 h-4" />
            )}
            {!sidebarCollapsed && (
              <span className="text-xs">{theme === "dark" ? "Light" : "Dark"}</span>
            )}
          </button>

          {/* Collapse toggle */}
          <button
            onClick={toggleSidebar}
            className={cn(
              "flex items-center gap-2 px-2 py-1.5 rounded-[var(--radius-sm)] text-[var(--color-text-muted)] hover:bg-[var(--color-bg-hover)] hover:text-[var(--color-text-secondary)] transition-all duration-200 cursor-pointer",
              sidebarCollapsed && "px-0 justify-center w-full"
            )}
            title={sidebarCollapsed ? "Expand sidebar" : "Collapse sidebar"}
          >
            {sidebarCollapsed ? (
              <PanelLeftOpen className="w-4 h-4" />
            ) : (
              <>
                <PanelLeftClose className="w-4 h-4" />
                <span className="text-xs">Collapse</span>
              </>
            )}
          </button>
        </div>
      </div>

      {showAdvertise && <AdvertiseDialog onClose={() => setShowAdvertise(false)} />}
    </aside>
  );
}