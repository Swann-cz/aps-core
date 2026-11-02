import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { App as AntdApp, ConfigProvider } from 'antd'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import type { ThemeConfig } from 'antd'
import { AppLayout } from './AppLayout'
import zhCN from 'antd/locale/zh_CN'
import { CoreProvider } from './CoreContext'
import { AnnualOverview } from '../pages/AnnualOverview'
import { MonthlyFilling } from '../pages/MonthlyFilling'
import { PlanningConditions } from '../pages/PlanningConditions'
import { NewPlan } from '../pages/NewPlan'
import { FormalVersions } from '../pages/FormalVersions'
import { Wizard } from '../pages/Wizard'

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } },
})

// 工业风精修（redesign-preserve）：单一深钢蓝主色 + 统一中性色 + 全局数字等宽。
// 语义色（成功/警告/危险、条件点红/紫/蓝）由业务组件自带，不在主题层覆盖。
const appTheme: ThemeConfig = {
  token: {
    colorPrimary: '#1d5fb8',
    colorInfo: '#1d5fb8',
    colorLink: '#1d5fb8',
    colorLinkHover: '#3a7ad0',
    colorLinkActive: '#154a8f',
    colorSuccess: '#1a8f5c',
    colorWarning: '#d98e14',
    colorError: '#d64545',
    colorBgLayout: '#eef2f8',
    colorBgContainer: '#ffffff',
    colorBgElevated: '#ffffff',
    colorBorder: '#d8e1ee',
    colorBorderSecondary: '#e8eef6',
    colorSplit: '#e8eef6',
    colorText: '#1c2a42',
    colorTextSecondary: '#54637e',
    colorTextTertiary: '#8b99b0',
    borderRadius: 6,
    borderRadiusSM: 4,
    fontSize: 15,
    controlHeight: 40,
    fontFamily: '"Segoe UI Variable", "Segoe UI", "PingFang SC", "HarmonyOS Sans SC", "Microsoft YaHei UI", "Microsoft YaHei", sans-serif',
  },
  components: {
    Layout: {
      siderBg: '#ffffff',
      headerBg: '#ffffff',
      headerHeight: 56,
      headerPadding: '0 20px',
    },
    Menu: {
      itemHeight: 38,
      itemBorderRadius: 8,
      itemMarginInline: 8,
      itemColor: '#3f4e68',
      itemHoverColor: '#1d5fb8',
      itemSelectedColor: '#154a8f',
      itemSelectedBg: '#e6f0fc',
      itemActiveBg: '#eef4fb',
      groupTitleColor: '#93a1b8',
      iconSize: 15,
    },
    Card: {
      headerFontSize: 14,
      paddingLG: 16,
      padding: 14,
    },
    Table: {
      headerBg: '#f4f8fd',
      headerColor: '#45536e',
      headerSplitColor: 'transparent',
      rowHoverBg: '#f5f9ff',
      cellPaddingBlock: 8,
      cellPaddingInline: 12,
    },
    Button: { fontWeight: 500 },
    Tag: { defaultBg: '#f5f8fc', defaultColor: '#3f4e68' },
    Tabs: { inkBarColor: '#1d5fb8', itemSelectedColor: '#1d5fb8' },
    Drawer: { colorBgElevated: '#ffffff' },
  },
}

export function App() {
  return <QueryClientProvider client={queryClient}>
    <ConfigProvider theme={appTheme} locale={zhCN}>
      <AntdApp><BrowserRouter><CoreProvider><AppLayout>
        <Routes>
          <Route path="/wizard" element={<Wizard />} />
          <Route path="/new-plan" element={<NewPlan />} />
          <Route path="/formal" element={<FormalVersions />} />
          <Route path="/annual-overview" element={<AnnualOverview />} />
          <Route path="/monthly-filling" element={<MonthlyFilling />} />
          <Route path="/planning-conditions" element={<PlanningConditions />} />
          <Route path="*" element={<Navigate to="/wizard" replace />} />
        </Routes>
      </AppLayout></CoreProvider></BrowserRouter></AntdApp>
    </ConfigProvider>
  </QueryClientProvider>
}
