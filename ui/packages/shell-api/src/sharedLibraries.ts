/**
 * WHAT EVERY MODULE IS PROMISED (BLOCKING.md item 3, step 1.2; decided
 * 21 October: "the kit's own dependencies"). A module built apart from
 * this page leaves these as bare imports and gets THIS page's copy
 * through the import map (@shell/build/sharedLibraries); anything else it
 * bundles itself. Adding a library here is a promise to every module;
 * removing one breaks the modules that use it.
 *
 * IN THE KIT, so a module's own build reads it by name
 * (`@elysium/shell-api/sharedLibraries`) -- Elysium's page and every
 * module agree on one list, and no package reaches into another's files.
 *
 * WHY THESE MUST BE SHARED, not merely may be: React and React DOM
 * because two copies cannot render one tree ("Invalid hook call"); the
 * router because a module's links and hooks must see the page's router;
 * Blueprint's core because its popovers and dialogs need the page's
 * `OverlaysProvider`, which a second copy would not see; the kit
 * (`@elysium/shell-api`) because it keeps state at module level -- the
 * session-expiry handler, the last configuration generation seen; and
 * ECharts so a module can add a chart type to the copy the kit's Chart
 * draws with.
 *
 * NOT `@blueprintjs/icons`, measured: it is two files of 830 KB and
 * 600 KB, and the page uses a few icons from each, so sharing it -- which
 * means sharing it whole -- put all of it on every first load. Icons
 * hold no state a module and the page must agree on; a module that wants
 * an icon component bundles that icon.
 *
 * WHAT IT COSTS, measured on the built page: the first load went from
 * 131 KB to 229 KB compressed. Blueprint's core and the router are shared
 * whole, because a module may use any part of them. ECharts costs
 * nothing until a module asks for it: shared libraries load lazily.
 */
export const SHARED_LIBRARIES = [
  'react',
  'react/jsx-runtime',
  'react/jsx-dev-runtime',
  'react-dom',
  'react-dom/client',
  'react-router-dom',
  // react-router-dom re-exports this: a module importing it directly must
  // get the page's router too, not a second copy whose hooks see no
  // router at all.
  'react-router',
  '@blueprintjs/core',
  'echarts/core',
  'echarts/charts',
  'echarts/components',
  'echarts/renderers',
]

/** Packages of our own whose every entry is shared. */
export const SHARED_PACKAGES = ['@shell/core', '@elysium/shell-api']
