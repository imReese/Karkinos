import { useEffect, useMemo, useState, type FormEvent } from 'react';

import {
  useAccountOverviewQuery,
  useMarketDataHealthQuery,
} from '../settings-feature-boundary';
import { useCopy } from '../../../shared/i18n/context';
import { usePreferences } from '../../../shared/preferences/context';
import {
  useAssetMetadataStatusQuery,
  useDataSourceStatusQuery,
  useLiveStatusQuery,
  useSettingsQuery,
  useStartLiveMutation,
  useStopLiveMutation,
  useTestNotificationMutation,
  useUpdateDataSourceSettingsMutation,
  useUpdateSettingsMutation,
} from '../api';
import {
  buildSettingsMarketModel,
  buildSettingsOperationsModel,
  type ManualTaskId,
} from './settings-page-model';

function dailyTaskKey() {
  return `karkinos.tushareDailyTasks.${new Date().toISOString().slice(0, 10)}`;
}

export function useSettingsPageController() {
  const copy = useCopy();
  const settings = useSettingsQuery();
  const dataSourceStatus = useDataSourceStatusQuery();
  const assetMetadataStatus = useAssetMetadataStatusQuery();
  const liveStatus = useLiveStatusQuery();
  const marketHealth = useMarketDataHealthQuery();
  const overview = useAccountOverviewQuery();
  const updateDataSource = useUpdateDataSourceSettingsMutation();
  const updateSettings = useUpdateSettingsMutation();
  const startLive = useStartLiveMutation();
  const stopLive = useStopLiveMutation();
  const testNotification = useTestNotificationMutation();
  const { locale, setLocale, theme, setTheme } = usePreferences();
  const fundNavCapabilityLabel =
    locale === 'zh' ? '基金净值接口' : 'Fund NAV capability';
  const [dataSource, setDataSource] = useState('');
  const [pollInterval, setPollInterval] = useState('60');
  const [accountCommissionRate, setAccountCommissionRate] = useState('0.0001');
  const [accountMinCommission, setAccountMinCommission] = useState('5');
  const taskStorageKey = useMemo(() => dailyTaskKey(), []);
  const [manualTasksDone, setManualTasksDone] = useState<
    Partial<Record<ManualTaskId, boolean>>
  >(() => {
    try {
      return JSON.parse(window.localStorage.getItem(taskStorageKey) ?? '{}');
    } catch {
      return {};
    }
  });

  useEffect(() => {
    if (!settings.data) {
      return;
    }
    setDataSource(settings.data.data_source);
    setPollInterval(String(settings.data.live_poll_interval));
    setAccountCommissionRate(String(settings.data.account_commission_rate));
    setAccountMinCommission(String(settings.data.account_min_commission));
  }, [settings.data]);

  useEffect(() => {
    window.localStorage.setItem(
      taskStorageKey,
      JSON.stringify(manualTasksDone),
    );
  }, [manualTasksDone, taskStorageKey]);

  const modelInputs = {
    copy,
    locale,
    settings,
    dataSourceStatus,
    assetMetadataStatus,
    liveStatus,
    marketHealth,
    overview,
    pollInterval,
  };
  const marketModel = buildSettingsMarketModel(modelInputs);
  const operationsModel = buildSettingsOperationsModel(
    modelInputs,
    marketModel,
  );

  const dataSourceChanged = useMemo(() => {
    if (!settings.data) {
      return false;
    }
    return (
      dataSource !== settings.data.data_source ||
      Number(pollInterval) !== settings.data.live_poll_interval
    );
  }, [dataSource, pollInterval, settings.data]);

  const accountCommissionChanged = useMemo(() => {
    if (!settings.data) {
      return false;
    }
    return (
      Number(accountCommissionRate) !== settings.data.account_commission_rate ||
      Number(accountMinCommission) !== settings.data.account_min_commission
    );
  }, [accountCommissionRate, accountMinCommission, settings.data]);

  const submitDataSource = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const normalizedInterval = Math.max(Number(pollInterval) || 60, 15);
    await updateDataSource.mutateAsync({
      data_source: dataSource.trim() || settings.data?.data_source || 'akshare',
      live_poll_interval: normalizedInterval,
    });
    setPollInterval(String(normalizedInterval));
  };

  const submitAccountCommission = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!settings.data) {
      return;
    }
    const normalizedRate = Math.max(Number(accountCommissionRate) || 0, 0);
    const normalizedMinimum = Math.max(Number(accountMinCommission) || 0, 0);
    await updateSettings.mutateAsync({
      ...settings.data,
      account_commission_rate: normalizedRate,
      account_min_commission: normalizedMinimum,
    });
    setAccountCommissionRate(String(normalizedRate));
    setAccountMinCommission(String(normalizedMinimum));
  };

  return {
    copy,
    settings,
    dataSourceStatus,
    assetMetadataStatus,
    liveStatus,
    marketHealth,
    overview,
    updateDataSource,
    updateSettings,
    startLive,
    stopLive,
    testNotification,
    locale,
    setLocale,
    theme,
    setTheme,
    fundNavCapabilityLabel,
    dataSource,
    setDataSource,
    pollInterval,
    setPollInterval,
    accountCommissionRate,
    setAccountCommissionRate,
    accountMinCommission,
    setAccountMinCommission,
    manualTasksDone,
    setManualTasksDone,
    ...marketModel,
    ...operationsModel,
    dataSourceChanged,
    accountCommissionChanged,
    submitDataSource,
    submitAccountCommission,
  };
}

export type SettingsPageController = ReturnType<
  typeof useSettingsPageController
>;
