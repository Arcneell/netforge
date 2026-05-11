import { ref, watch, type Ref } from 'vue'

export function useDebounce<T>(source: Ref<T>, delayMs = 250): Ref<T> {
  const debounced = ref(source.value) as Ref<T>
  let timer: ReturnType<typeof setTimeout> | null = null

  watch(source, (value) => {
    if (timer) clearTimeout(timer)
    timer = setTimeout(() => {
      debounced.value = value
    }, delayMs)
  })

  return debounced
}
