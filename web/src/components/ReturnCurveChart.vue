<template>
  <div ref="chartRef" class="return-chart"></div>
</template>

<script setup lang="ts">
import { onMounted, onUnmounted, ref, watch } from 'vue'
import * as echarts from 'echarts/core'
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import { LineChart } from 'echarts/charts'
import { CanvasRenderer } from 'echarts/renderers'

echarts.use([LineChart, GridComponent, LegendComponent, TooltipComponent, CanvasRenderer])

interface ReturnPoint {
  timestamp: string
  value: number
}

interface ReturnSeries {
  name: string
  points: ReturnPoint[]
}

const props = defineProps<{
  series: ReturnSeries[]
}>()

const chartRef = ref<HTMLDivElement>()
let chart: echarts.ECharts | null = null

function updateChart() {
  if (!chart) return
  if (!props.series.length) {
    chart.clear()
    return
  }

  const xAxis = props.series[0]?.points.map((point) => point.timestamp.slice(0, 10)) ?? []
  chart.setOption({
    tooltip: {
      trigger: 'axis',
      valueFormatter: (value: number) => `${value.toFixed(2)}%`,
      backgroundColor: 'rgba(22, 22, 22, 0.95)',
      borderColor: '#27272a',
      textStyle: { color: '#ededed' },
    },
    legend: {
      top: 0,
      textStyle: { color: '#6b7280', fontSize: 11 },
    },
    grid: {
      left: 52,
      right: 20,
      top: 40,
      bottom: 28,
    },
    xAxis: {
      type: 'category',
      data: xAxis,
      boundaryGap: false,
      axisLabel: { fontSize: 10, color: '#8a94a6' },
      axisLine: { lineStyle: { color: '#d7dde6' } },
    },
    yAxis: {
      type: 'value',
      axisLabel: {
        fontSize: 11,
        color: '#8a94a6',
        formatter: (value: number) => `${value.toFixed(0)}%`,
      },
      splitLine: { lineStyle: { color: 'rgba(15, 23, 42, 0.08)' } },
    },
    series: props.series.map((series) => ({
      name: series.name,
      type: 'line',
      smooth: true,
      showSymbol: false,
      emphasis: { focus: 'series' },
      lineStyle: { width: 2 },
      data: series.points.map((point) => Number((point.value * 100).toFixed(2))),
    })),
  })
}

function onResize() {
  chart?.resize()
}

onMounted(() => {
  if (chartRef.value) {
    chart = echarts.init(chartRef.value, undefined, { renderer: 'canvas' })
    updateChart()
  }
  window.addEventListener('resize', onResize)
})

watch(() => props.series, updateChart, { deep: true })

onUnmounted(() => {
  window.removeEventListener('resize', onResize)
  chart?.dispose()
  chart = null
})
</script>

<style scoped>
.return-chart {
  width: 100%;
  height: 320px;
}
</style>
