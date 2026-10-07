import { apiClient, useMock, wait } from './client'
import { dashboardSummary, effectStats, propertyStats, recentStats, splitStats } from '../data/mockDashboard'
import type { DashboardSummary } from '../types/dashboard'
export async function getDashboardSummary(): Promise<DashboardSummary> { if (!useMock) return (await apiClient.get<DashboardSummary>('/api/v1/dashboard/summary')).data; await wait(200); return dashboardSummary }
export async function getDashboardCharts() { if (!useMock) return (await apiClient.get('/api/v1/dashboard/charts')).data; await wait(200); return { effectStats, propertyStats, splitStats, recentStats } }
