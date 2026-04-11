<template>
  <div ref="chartRef" style="width: 100%; height: 300px;"></div>
</template>

<script setup lang="ts">
import { ref, onMounted, watch } from 'vue'
import * as echarts from 'echarts/core'
import { PieChart } from 'echarts/charts'
import { TooltipComponent, LegendComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

echarts.use([PieChart, TooltipComponent, LegendComponent, CanvasRenderer])

const props = defineProps<{
  data: Array<{ name: string; value: number; itemStyle?: Record<string, string> }>
}>()

const chartRef = ref<HTMLDivElement>()
let chart: echarts.ECharts | null = null

const COLORS = ['#6366f1', '#8b5cf6', '#22c55e', '#f59e0b', '#3b82f6', '#ef4444', '#38bdf8', '#a855f7']

onMounted(() => {
  if (chartRef.value) {
    chart = echarts.init(chartRef.value, undefined, { renderer: 'canvas' })
    updateChart()
  }
})

watch(() => props.data, updateChart, { deep: true })

function updateChart() {
  if (!chart) return
  chart.setOption({
    tooltip: {
      trigger: 'item',
      formatter: '{b}: {d}%',
      backgroundColor: 'rgba(26, 27, 35, 0.95)',
      borderColor: 'var(--border)',
      textStyle: { color: '#e4e4e7' },
    },
    legend: {
      bottom: 0,
      type: 'scroll',
      textStyle: { color: '#a1a1aa', fontSize: 12 },
    },
    series: [{
      type: 'pie',
      radius: ['40%', '70%'],
      center: ['50%', '45%'],
      avoidLabelOverlap: true,
      itemStyle: {
        borderRadius: 6,
        borderColor: '#1a1b23',
        borderWidth: 2,
      },
      label: {
        show: true,
        formatter: '{b}\n{d}%',
        color: '#a1a1aa',
        fontSize: 11,
      },
      data: props.data.map((item, i) => ({
        ...item,
        itemStyle: item.itemStyle || { color: COLORS[i % COLORS.length] },
      })),
    }],
  })
}

window.addEventListener('resize', () => chart?.resize())
</script>
