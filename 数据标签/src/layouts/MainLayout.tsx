import { Outlet } from 'react-router-dom'
import { Header } from '../components/common/Header'
import { Footer } from '../components/common/Footer'
export function MainLayout() { return <><Header/><main><Outlet/></main><Footer/></> }
