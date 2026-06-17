import { useLang } from '../i18n'

// A tiny language toggle: shows the language you'd switch TO, so it reads like
// an action. Persisted via the store, so the whole app re-renders on click.
export default function LangSwitch() {
  const { lang, toggle } = useLang()
  return (
    <button className="lang-switch" onClick={toggle} title="切换语言 / Switch language">
      {lang === 'zh' ? 'EN' : '中'}
    </button>
  )
}
