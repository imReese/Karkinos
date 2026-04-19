<template>
  <div ref="chartRef" style="width: 100%; height: 400px;"></div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch } from 'vue'
import * as echarts from 'echarts/core'
import { CandlestickChart, BarChart, LineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, DataZoomComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

echarts.use([CandlestickChart, BarChart, LineChart, GridComponent, TooltipComponent, DataZoomComponent, CanvasRenderer])

const props = defineProps<{
  data: Array<{ timestamp: string; open: number; high: number; low: number; close: number; volume: number }>
}>()

const chartRef = ref<HTMLDivElement>()
let chart: echarts.ECharts | null = null

onMounted(() => {
  if (chartRef.value) {
    chart = echarts.init(chartRef.value, undefined, { renderer: 'canvas' })
    updateChart()
  }
})

watch(() => props.data, updateChart, { deep: true })

function updateChart() {
  if (!chart) return
  if (!props.data.length) {
    chart.clear()
    return
  }
  const intraday = props.data.some((point) => point.timestamp.includes('T'))
  const dates = props.data.map((d) =>
    intraday ? d.timestamp.slice(11, 16) : d.timestamp.slice(0, 10),
  )
  const closes = props.data.map((d) => d.close)
  const ohlc = props.data.map((d) => [d.open, d.close, d.low, d.high])
  const volumes = props.data.map((d) => d.volume)

  if (intraday) {
    const previousClose = props.data[0]?.open ?? props.data[0]?.close ?? 0
    chart.setOption({
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'cross' },
        backgroundColor: 'rgba(22, 22, 22, 0.95)',
        borderColor: '#27272a',
        textStyle: { color: '#ededed' },
        valueFormatter: (value: number) => value?.toFixed?.(2) ?? String(value),
      },
      grid: [{ left: 24, right: 24, top: 20, bottom: 44 }],
      xAxis: {
        type: 'category',
        data: dates,
        boundaryGap: false,
        axisLabel: { fontSize: 11, color: '#71717a' },
        axisLine: { lineStyle: { color: 'rgba(15, 23, 42, 0.08)' } },
        axisTick: { show: false },
      },
      yAxis: {
        type: 'value',
        scale: true,
        axisLabel: { fontSize: 11, color: '#71717a' },
        splitLine: { lineStyle: { color: 'rgba(15, 23, 42, 0.06)' } },
      },
      dataZoom: [{ type: 'inside', xAxisIndex: 0 }],
      series: [
        {
          type: 'line',
          smooth: true,
          showSymbol: false,
          data: closes,
          lineStyle: { width: 2, color: '#ef4444' },
          areaStyle: {
            color: {
              type: 'linear',
              x: 0,
              y: 0,
              x2: 0,
              y2: 1,
              colorStops: [
                { offset: 0, color: 'rgba(239, 68, 68, 0.28)' },
                { offset: 1, color: 'rgba(239, 68, 68, 0.02)' },
              ],
            },
          },
          markLine: previousClose
            ? {
                symbol: 'none',
                lineStyle: {
                  color: 'rgba(113, 113, 122, 0.48)',
                  type: 'dashed',
                },
                label: {
                  show: true,
                  formatter: `昨收 ${previousClose.toFixed(2)}`,
                  color: '#71717a',
                },
                data: [{ yAxis: previousClose }],
              }
            : undefined,
        },
      ],
    })
    return
  }

  chart.setOption({
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross' },
      backgroundColor: 'rgba(22, 22, 22, 0.95)',
      borderColor: '#27272a',
      textStyle: { color: '#ededed' },
    },
    grid: [
      { left: 80, right: 24, top: 16, height: '55%' },
      { left: 80, right: 24, top: '72%', height: '20%' },
    ],
    xAxis: [
      { type: 'category', data: dates, gridIndex: 0, axisLabel: { show: false }, axisLine: { lineStyle: { color: '#27272a' } } },
      { type: 'category', data: dates, gridIndex: 1, axisLabel: { fontSize: 10, color: '#71717a' }, axisLine: { lineStyle: { color: '#27272a' } } },
    ],
    yAxis: [
      { type: 'value', gridIndex: 0, scale: true, axisLabel: { fontSize: 11, color: '#71717a' }, splitLine: { lineStyle: { color: '#27272a' } } },
      { type: 'value', gridIndex: 1, axisLabel: { show: false }, splitLine: { show: false } },
    ],
    dataZoom: [{ type: 'inside', xAxisIndex: [0, 1] }],
    series: [
      {
        type: 'candlestick',
        data: ohlc,
        xAxisIndex: 0,
        yAxisIndex: 0,
        itemStyle: {
          color: '#ef4444',
          color0: '#22c55e',
          borderColor: '#ef4444',
          borderColor0: '#22c55e',
        },
      },
      {
        type: 'bar',
        data: volumes,
        xAxisIndex: 1,
        yAxisIndex: 1,
        itemStyle: { color: '#71717a' },
      },
    ],
  })
}

function onResize() {
  chart?.resize()
}

window.addEventListener('resize', onResize)

onUnmounted(() => {
  window.removeEventListener('resize', onResize)
  if (chart) {
    chart.dispose()
    chart = null
  }
})
</script>
