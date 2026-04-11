<template>
  <div ref="chartRef" style="width: 100%; height: 350px;"></div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch } from 'vue'
import * as echarts from 'echarts/core'
import { LineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, DataZoomComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

echarts.use([LineChart, GridComponent, TooltipComponent, DataZoomComponent, CanvasRenderer])

const props = defineProps<{
  data: Array<{ timestamp: string; equity: number }>
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
  if (!chart || !props.data.length) return
  const dates = props.data.map(d => d.timestamp.slice(0, 10))
  const values = props.data.map(d => d.equity)

  chart.setOption({
    tooltip: {
      trigger: 'axis',
      backgroundColor: 'rgba(26, 27, 35, 0.95)',
      borderColor: '#2a2b3a',
      textStyle: { color: '#e4e4e7' },
      formatter: (params: any) => {
        const p = params[0]
        return `${p.axisValue}<br/>权益: ¥${Number(p.value).toLocaleString('zh-CN', { minimumFractionDigits: 2 })}`
      },
    },
    grid: { left: 80, right: 20, top: 20, bottom: 60 },
    xAxis: {
      type: 'category',
      data: dates,
      axisLabel: { fontSize: 11, color: '#71717a' },
      axisLine: { lineStyle: { color: '#2a2b3a' } },
    },
    yAxis: {
      type: 'value',
      axisLabel: {
        fontSize: 11,
        color: '#71717a',
        formatter: (v: number) => `¥${(v / 10000).toFixed(0)}万`,
      },
      splitLine: { lineStyle: { color: '#2a2b3a' } },
    },
    dataZoom: [{ type: 'inside' }],
    series: [{
      type: 'line',
      data: values,
      smooth: true,
      lineStyle: { color: '#6366f1', width: 2 },
      areaStyle: {
        color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
          { offset: 0, color: 'rgba(99, 102, 241, 0.3)' },
          { offset: 1, color: 'rgba(99, 102, 241, 0.02)' },
        ]),
      },
    }],
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
