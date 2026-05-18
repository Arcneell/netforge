import type { Page, PageParams } from '@/api/types'

/**
 * Fetch every page of a paginated endpoint and return the concatenated list.
 *
 * The backend caps `page_size` at 200 to keep individual responses bounded,
 * which means a site with > 200 switches or rooms would silently truncate
 * the topology graph if the UI only requested the first page. This helper
 * issues N sequential requests until the API reports we've seen everything.
 *
 * Sequential rather than parallel because `total` is only known after the
 * first response — paralleling would require either a separate count call
 * or guessing the page count, both of which are worse than the few extra
 * round-trips on the rare path where pagination matters.
 *
 * Safety cap of `maxPages` to avoid an infinite loop if the backend ever
 * lies about `total`. Tuned so we never quietly exceed ~10 000 items.
 */
export async function fetchAllPages<T, P extends PageParams = PageParams>(
  fetcher: (params: P) => Promise<Page<T>>,
  params: Omit<P, 'page' | 'page_size'> = {} as Omit<P, 'page' | 'page_size'>,
  maxPages = 50,
): Promise<T[]> {
  const pageSize = 200
  const out: T[] = []
  for (let page = 1; page <= maxPages; page++) {
    const res = await fetcher({ ...(params as object), page, page_size: pageSize } as P)
    out.push(...res.items)
    // Two reasons to stop: we got fewer rows than requested (last page), OR
    // we've collected at least the reported total (defensive on `total`
    // accuracy — some endpoints recount per-query and the value can shift
    // mid-iteration).
    if (res.items.length < pageSize || out.length >= res.total) break
  }
  return out
}
