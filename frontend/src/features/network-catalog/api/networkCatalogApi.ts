/** 组网配套目录（配件库）API。 */
import { del, get, post, put } from '@/shared/api/client';
import type { OkData } from '@/shared/types';
import type { NetworkCatalogItem } from '@/shared/types';

export function listNetworkCatalog(): Promise<NetworkCatalogItem[]> {
  return get<NetworkCatalogItem[]>('/network-catalog');
}

export function createNetworkCatalogItem(payload: Record<string, unknown>): Promise<NetworkCatalogItem> {
  return post<NetworkCatalogItem>('/network-catalog', payload);
}

export function updateNetworkCatalogItem(
  id: number,
  payload: Record<string, unknown>,
): Promise<NetworkCatalogItem> {
  return put<NetworkCatalogItem>(`/network-catalog/${id}`, payload);
}

export function deleteNetworkCatalogItem(id: number): Promise<OkData> {
  return del<OkData>(`/network-catalog/${id}`);
}
