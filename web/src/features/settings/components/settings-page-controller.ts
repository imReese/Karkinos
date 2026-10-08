import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react';

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
  const testNotification = useTestNotificationMutation();
  const { locale, setLocale, theme, setTheme } = usePreferences();
  const fundNavCapabilityLabel =
    locale === 'zh' ? '基金净值接口' : 'Fund NAV capability';
  const [dataSource, setDataSourceValue] = useState('');
  const dataSourceDirty = useRef(false);
  const accountCostsDirty = useRef(false);
  const [accountCostsError, setAccountCostsError] = useState('');
  const [dataSettingsError, setDataSettingsError] = useState('');
  const [pollInterval, setPollIntervalValue] = useState('60');
  const [accountCommissionRate, setAccountCommissionRateValue] =
    useState('0.0001');
  const [accountMinCommission, setAccountMinCommissionValue] = useState('5');
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
    if (!dataSourceDirty.current) {
      setDataSourceValue(settings.data.data_source);
      setPollIntervalValue(String(settings.data.live_poll_interval));
    }
    if (!accountCostsDirty.current) {
      setAccountCommissionRateValue(
        String(settings.data.account_commission_rate),
      );
      setAccountMinCommissionValue(
        String(settings.data.account_min_commission),
      );
    }
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

  const setDataSource = (value: string) => {
    dataSourceDirty.current = true;
    updateDataSource.reset();
    setDataSettingsError('');
    setDataSourceValue(value);
  };
  const setPollInterval = (value: string) => {
    dataSourceDirty.current = true;
    updateDataSource.reset();
    setDataSettingsError('');
    setPollIntervalValue(value);
  };
  const setAccountCommissionRate = (value: string) => {
    accountCostsDirty.current = true;
    updateSettings.reset();
    setAccountCostsError('');
    setAccountCommissionRateValue(value);
  };
  const setAccountMinCommission = (value: string) => {
    accountCostsDirty.current = true;
    updateSettings.reset();
    setAccountCostsError('');
    setAccountMinCommissionValue(value);
  };
  const accountCostsValid = [accountCommissionRate, accountMinCommission].every(
    (value) =>
      value.trim() !== '' &&
      Number.isFinite(Number(value)) &&
      Number(value) >= 0,
  );
  const dataSettingsValid =
    dataSource.trim() !== '' &&
    pollInterval.trim() !== '' &&
    Number.isSafeInteger(Number(pollInterval)) &&
    Number(pollInterval) >= 15;

  const submitDataSource = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!settings.data || updateDataSource.isPending) return;
    if (!dataSettingsValid) {
      setDataSettingsError(copy.settings.invalidDataSettings);
      return;
    }
    try {
      const saved = await updateDataSource.mutateAsync({
        data_source: dataSource,
        live_poll_interval: Number(pollInterval),
      });
      dataSourceDirty.current = false;
      setDataSourceValue(saved.data_source);
      setPollIntervalValue(String(saved.live_poll_interval));
    } catch {
      // The mutation state keeps the error visible and the draft retryable.
    }
  };

  const submitAccountCommission = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!settings.data || updateSettings.isPending) return;
    if (!accountCostsValid) {
      setAccountCostsError(copy.settings.invalidAccountCosts);
      return;
    }
    try {
      const saved = await updateSettings.mutateAsync({
        account_commission_rate: Number(accountCommissionRate),
        account_min_commission: Number(accountMinCommission),
      });
      accountCostsDirty.current = false;
      setAccountCommissionRateValue(String(saved.account_commission_rate));
      setAccountMinCommissionValue(String(saved.account_min_commission));
    } catch {
      // The mutation state keeps the error visible and the draft retryable.
    }
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
    accountCostsValid,
    accountCostsError,
    dataSettingsValid,
    dataSettingsError,
    submitDataSource,
    submitAccountCommission,
  };
}

export type SettingsPageController = ReturnType<
  typeof useSettingsPageController
>;
