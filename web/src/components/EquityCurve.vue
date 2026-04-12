<template>
  <div ref="chartRef" style="width: 100%; height: 350px;"></div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch } from 'vue'
import * as echarts from 'echarts/core'
import { LineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, DataZoomComponent, LegendComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

echarts.use([LineChart, GridComponent, TooltipComponent, DataZoomComponent, LegendComponent, CanvasRenderer])

interface EquityDataPoint {
  timestamp: string
  equity: number
}

interface EquitySeries {
  name: string
  data: EquityDataPoint[]
}

const props = defineProps<{
  data?: EquityDataPoint[]
  series?: EquitySeries[]
}>()

const COLORS = ['#6366f1', '#34d399', '#fbbf24', '#f43f5e', '#a78bfa', '#22d3ee']

const chartRef = ref<HTMLDivElement>()
let chart: echarts.ECharts | null = null

onMounted(() => {
  if (chartRef.value) {
    chart = echarts.init(chartRef.value, undefined, { renderer: 'canvas' })
    updateChart()
  }
})

watch(() => [props.data, props.series], updateChart, { deep: true })

function updateChart() {
  if (!chart) return

  // Multi-series mode
  if (props.series && props.series.length > 0) {
    const allDates = new Set<string>()
    for (const s of props.series) {
      for (const d of s.data) {
        allDates.add(d.timestamp.slice(0, 10))
      }
    }
    const dates = [...allDates].sort()

    const chartSeries = props.series.map((s, i) => ({
      type: 'line' as const,
      name: s.name,
      data: dates.map(date => {
        const point = s.data.find(d => d.timestamp.slice(0, 10) === date)
        return point ? point.equity : null
      }),
      smooth: true,
      lineStyle: { color: COLORS[i % COLORS.length], width: 2 },
      itemStyle: { color: COLORS[i % COLORS.length] },
      connectNulls: true,
    }))

    chart.setOption({
      tooltip: {
        trigger: 'axis',
        backgroundColor: 'rgba(22, 22, 22, 0.95)',
        borderColor: '#27272a',
        textStyle: { color: '#ededed' },
        formatter: (params: any) => {
          if (!Array.isArray(params)) return ''
          let html = `${params[0]?.axisValue}<br/>`
          for (const p of params) {
            if (p.value != null) {
              html += `${p.marker} ${p.seriesName}: ¥${Number(p.value).toLocaleString('zh-CN', { minimumFractionDigits: 2 })}<br/>`
            }
          }
          return html
        },
      },
      legend: {
        data: props.series.map(s => s.name),
        textStyle: { color: '#a1a1aa', fontSize: 12 },
        top: 0,
      },
      grid: { left: 80, right: 24, top: 40, bottom: 48 },
      xAxis: {
        type: 'category',
        data: dates,
        axisLabel: { fontSize: 11, color: '#71717a' },
        axisLine: { lineStyle: { color: '#27272a' } },
      },
      yAxis: {
        type: 'value',
        axisLabel: {
          fontSize: 11,
          color: '#71717a',
          formatter: (v: number) => `¥${(v / 10000).toFixed(0)}万`,
        },
        splitLine: { lineStyle: { color: '#27272a' } },
      },
      dataZoom: [{ type: 'inside' }],
      series: chartSeries,
    }, true)
    return
  }

  // Single-series mode
  if (!props.data || !props.data.length) return
  const dates = props.data.map(d => d.timestamp.slice(0, 10))
  const values = props.data.map(d => d.equity)

  chart.setOption({
    tooltip: {
      trigger: 'axis',
      backgroundColor: 'rgba(22, 22, 22, 0.95)',
      borderColor: '#27272a',
      textStyle: { color: '#ededed' },
      formatter: (params: any) => {
        const p = params[0]
        return `${p.axisValue}<br/>权益: ¥${Number(p.value).toLocaleString('zh-CN', { minimumFractionDigits: 2 })}`
      },
    },
    grid: { left: 80, right: 24, top: 24, bottom: 48 },
    xAxis: {
      type: 'category',
      data: dates,
      axisLabel: { fontSize: 11, color: '#71717a' },
      axisLine: { lineStyle: { color: '#27272a' } },
    },
    yAxis: {
      type: 'value',
      axisLabel: {
        fontSize: 11,
        color: '#71717a',
        formatter: (v: number) => `¥${(v / 10000).toFixed(0)}万`,
      },
      splitLine: { lineStyle: { color: '#27272a' } },
    },
    dataZoom: [{ type: 'inside' }],
    series: [{
      type: 'line',
      data: values,
      smooth: true,
      lineStyle: { color: '#6366f1', width: 2 },
      areaStyle: {
        color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
          { offset: 0, color: 'rgba(99, 102, 241, 0.2)' },
          { offset: 1, color: 'rgba(99, 102, 241, 0.01)' },
        ]),
      },
    }],
  }, true)
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
