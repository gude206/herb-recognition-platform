import { lazy, Suspense } from 'react'
import { BrowserRouter, Route, Routes } from 'react-router-dom'
import { MainLayout } from './layouts/MainLayout'
const HomePage = lazy(() => import('./pages/HomePage').then(module => ({default:module.HomePage})))
const HerbGalleryPage = lazy(() => import('./pages/HerbGalleryPage').then(module => ({default:module.HerbGalleryPage})))
const HerbDetailPage = lazy(() => import('./pages/HerbDetailPage').then(module => ({default:module.HerbDetailPage})))
const KnowledgePage = lazy(() => import('./pages/KnowledgePage').then(module => ({default:module.KnowledgePage})))
const LoginPage = lazy(() => import('./pages/LoginPage').then(module => ({default:module.LoginPage})))
const NotFoundPage = lazy(() => import('./pages/NotFoundPage').then(module => ({default:module.NotFoundPage})))
export default function App() { return <BrowserRouter><Suspense fallback={<div className="loading-box page-shell">正在展开本草页面…</div>}><Routes><Route element={<MainLayout/>}><Route path="/" element={<HomePage/>}/><Route path="/herbs" element={<HerbGalleryPage/>}/><Route path="/herbs/:id" element={<HerbDetailPage/>}/><Route path="/knowledge" element={<KnowledgePage/>}/><Route path="/login" element={<LoginPage/>}/><Route path="*" element={<NotFoundPage/>}/></Route></Routes></Suspense></BrowserRouter> }
