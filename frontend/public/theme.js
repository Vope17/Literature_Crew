// Apply the saved appearance before styles render to avoid a light/dark flash.
(() => {
  let preference = 'system'
  try {
    const saved = localStorage.getItem('literature-theme')
    if (['light', 'dark', 'system'].includes(saved)) preference = saved
  } catch { /* Use the system appearance when browser storage is unavailable. */ }
  const dark = window.matchMedia?.('(prefers-color-scheme: dark)').matches ?? false
  document.documentElement.dataset.themePreference = preference
  document.documentElement.dataset.theme = preference === 'system' ? (dark ? 'dark' : 'light') : preference
})()
