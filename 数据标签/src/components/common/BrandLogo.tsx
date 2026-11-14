import logo from '../../assets/brand/herb-logo.png'

/** The brand name is rendered as text beside this decorative mark. */
export function BrandLogo() {
  return <img className="brand-logo" src={logo} alt="" aria-hidden="true" width={48} height={30} decoding="async"/>
}
