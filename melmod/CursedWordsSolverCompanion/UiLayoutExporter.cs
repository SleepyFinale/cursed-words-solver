using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Reflection;
using System.Runtime.InteropServices;
using UnityEngine;

namespace CursedWordsSolverCompanion
{
    public sealed class UiLayoutSnapshot
    {
        public string coordinate_space = "screen_top_left";
        public int screen_w;
        public int screen_h;
        public UiBoardRectSnapshot board;
        public UiRackRectSnapshot consumable_rack;
    }

    public sealed class UiBoardRectSnapshot
    {
        public int x;
        public int y;
        public int width;
        public int height;
        public int rows = 5;
        public int cols = 5;
        public List<UiCellSnapshot> cells = new List<UiCellSnapshot>();
    }

    public sealed class UiRackRectSnapshot
    {
        public int x;
        public int y;
        public int width;
        public int height;
        public int slot_count = 5;
        public List<UiRackSlotSnapshot> rack_slots = new List<UiRackSlotSnapshot>();
    }

    public sealed class UiCellSnapshot
    {
        public int row;
        public int col;
        public int index;
        public int x;
        public int y;
    }

    public sealed class UiRackSlotSnapshot
    {
        public int rack_index;
        public int x;
        public int y;
        public int width;
        public int height;
    }

    /// <summary>
    /// Export board and consumable rack screen bounds for Python overlay alignment.
    /// Coordinates match Qt virtual-desktop space (top-left origin).
    /// </summary>
    public static class UiLayoutExporter
    {
        private const int DefaultGridSize = 5;
        private const int FirstRowConsumableSlots = 5;

        private static readonly BindingFlags MemberFlags =
            BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Public;

        /// <summary>Last export outcome for export_diagnostics.ui_layout_status.</summary>
        public static string LastStatus { get; private set; } = "";

        [StructLayout(LayoutKind.Sequential)]
        private struct RECT
        {
            public int Left;
            public int Top;
            public int Right;
            public int Bottom;
        }

        [StructLayout(LayoutKind.Sequential)]
        private struct POINT
        {
            public int X;
            public int Y;
        }

        [DllImport("user32.dll")]
        private static extern bool GetClientRect(IntPtr hWnd, out RECT lpRect);

        [DllImport("user32.dll")]
        private static extern bool ClientToScreen(IntPtr hWnd, ref POINT lpPoint);

        public static UiLayoutSnapshot TryExport(BoardSnapshot board)
        {
            LastStatus = "";
            if (board == null)
            {
                LastStatus = "board_snapshot_missing";
                return null;
            }

            try
            {
                var grid = UnityEngine.Object.FindAnyObjectByType<GridLayoutController>();
                if (grid == null)
                {
                    LastStatus = "grid_missing";
                    return null;
                }

                var cam = ResolveCamera();
                if (cam == null)
                {
                    LastStatus = "camera_missing";
                    return null;
                }

                if (!TryGetGameClientOrigin(out var originX, out var originY, out var clientW, out var clientH))
                {
                    LastStatus = "client_origin_failed";
                    return null;
                }

                var scaleX = clientW / (float)Mathf.Max(1, Screen.width);
                var scaleY = clientH / (float)Mathf.Max(1, Screen.height);

                var boardRect = BuildBoardRect(
                    grid,
                    cam,
                    originX,
                    originY,
                    clientH,
                    scaleX,
                    scaleY,
                    board
                );
                if (boardRect == null || boardRect.cells == null || boardRect.cells.Count == 0)
                {
                    LastStatus = "board_bounds_empty";
                    return null;
                }

                var rackRect = BuildRackRect(cam, originX, originY, clientH, scaleX, scaleY);
                if (rackRect == null)
                    LastStatus = "rack_bounds_empty";
                else
                    LastStatus = "ok";

                return new UiLayoutSnapshot
                {
                    coordinate_space = "screen_top_left",
                    screen_w = Screen.width,
                    screen_h = Screen.height,
                    board = boardRect,
                    consumable_rack = rackRect,
                };
            }
            catch (Exception ex)
            {
                LastStatus = "exception:" + ex.Message;
                CompanionDiagnostics.LogVerbose("UiLayoutExporter: " + ex.Message);
                return null;
            }
        }

        private static Camera ResolveCamera()
        {
            if (Camera.main != null)
                return Camera.main;

            var cameras = UnityEngine.Object.FindObjectsByType<Camera>(FindObjectsSortMode.None);
            if (cameras != null && cameras.Length > 0)
                return cameras[0];

            return null;
        }

        private static bool TryGetGameClientOrigin(
            out int originX,
            out int originY,
            out int clientW,
            out int clientH
        )
        {
            originX = 0;
            originY = 0;
            clientW = Screen.width;
            clientH = Screen.height;

            try
            {
                var hwnd = Process.GetCurrentProcess().MainWindowHandle;
                if (hwnd == IntPtr.Zero)
                    return true;

                RECT client;
                if (!GetClientRect(hwnd, out client))
                    return true;

                var topLeft = new POINT { X = 0, Y = 0 };
                if (!ClientToScreen(hwnd, ref topLeft))
                    return true;

                originX = topLeft.X;
                originY = topLeft.Y;
                clientW = Math.Max(1, client.Right - client.Left);
                clientH = Math.Max(1, client.Bottom - client.Top);
                return true;
            }
            catch
            {
                return true;
            }
        }

        private static UiBoardRectSnapshot BuildBoardRect(
            GridLayoutController grid,
            Camera cam,
            int originX,
            int originY,
            int clientH,
            float scaleX,
            float scaleY,
            BoardSnapshot board
        )
        {
            var tileObjects = grid.GetTileObjects();
            if (tileObjects == null || tileObjects.Count == 0)
                return null;

            float minX = float.MaxValue;
            float minY = float.MaxValue;
            float maxX = float.MinValue;
            float maxY = float.MinValue;
            var cells = new List<UiCellSnapshot>();
            var anyBounds = false;

            foreach (var tileObject in tileObjects)
            {
                if (tileObject == null)
                    continue;

                var coords = tileObject.GridCoordinate;
                var internalRow = coords.y;
                var col = coords.x;
                // Match BoardExporter: solver row 0 = top, Unity grid y = bottom.
                var displayRow = DefaultGridSize - 1 - internalRow;
                var index = displayRow * DefaultGridSize + col;

                if (!TryProjectTileCenter(
                    tileObject,
                    cam,
                    originX,
                    originY,
                    clientH,
                    scaleX,
                    scaleY,
                    out var centerX,
                    out var centerY
                ))
                    continue;

                cells.Add(
                    new UiCellSnapshot
                    {
                        row = displayRow,
                        col = col,
                        index = index,
                        x = Mathf.RoundToInt(centerX),
                        y = Mathf.RoundToInt(centerY),
                    }
                );

                if (AccumulateRendererBoundsInChildren(
                    tileObject.transform,
                    cam,
                    originX,
                    originY,
                    clientH,
                    scaleX,
                    scaleY,
                    ref minX,
                    ref minY,
                    ref maxX,
                    ref maxY
                ))
                    anyBounds = true;
            }

            // Always union tile centers so renderer-bounds glitches cannot collapse the rect.
            if (cells.Count > 0)
            {
                foreach (var cell in cells)
                {
                    minX = Mathf.Min(minX, cell.x);
                    minY = Mathf.Min(minY, cell.y);
                    maxX = Mathf.Max(maxX, cell.x);
                    maxY = Mathf.Max(maxY, cell.y);
                }
                anyBounds = true;
            }

            if (!anyBounds)
                return null;

            if (cells.Count >= 2)
            {
                var pitchX = (maxX - minX) / 4f;
                var pitchY = (maxY - minY) / 4f;
                if (pitchX > 1f)
                {
                    minX -= pitchX * 0.5f;
                    maxX += pitchX * 0.5f;
                }
                if (pitchY > 1f)
                {
                    minY -= pitchY * 0.5f;
                    maxY += pitchY * 0.5f;
                }
            }

            var width = Mathf.Max(1, Mathf.CeilToInt(maxX) - Mathf.FloorToInt(minX));
            var height = Mathf.Max(1, Mathf.CeilToInt(maxY) - Mathf.FloorToInt(minY));
            if ((width < 100 || height < 100) && cells.Count >= 20)
                LastStatus = "board_bounds_degenerate";

            return new UiBoardRectSnapshot
            {
                x = Mathf.FloorToInt(minX),
                y = Mathf.FloorToInt(minY),
                width = width,
                height = height,
                rows = board.rows > 0 ? board.rows : 5,
                cols = board.cols > 0 ? board.cols : 5,
                cells = cells,
            };
        }

        private static UiRackRectSnapshot BuildRackRect(
            Camera cam,
            int originX,
            int originY,
            int clientH,
            float scaleX,
            float scaleY
        )
        {
            var ivc = CharacterInfoPanel.SingletonInventoryVisualController;
            if (ivc == null)
                return null;

            var slots = GetTileSlotTransforms(ivc);
            if (slots == null || slots.Length == 0)
                return null;

            var slotEnd = ResolveConsumableSlotCount(ivc, slots.Length);
            var consumables = GetConsumableTileObjects(ivc);

            float minX = float.MaxValue;
            float minY = float.MaxValue;
            float maxX = float.MinValue;
            float maxY = float.MinValue;
            var rackSlots = new List<UiRackSlotSnapshot>();
            var any = false;

            for (var i = 0; i < slotEnd; i++)
            {
                Transform target = null;
                // Slot transforms are stable; consumable tiles can overlap mid-animation.
                if (i < slots.Length)
                    target = slots[i];

                if (target == null && consumables != null && i < consumables.Count && consumables[i] != null)
                    target = GetConsumableRectTransform(consumables[i]);

                if (target == null)
                    continue;

                if (AccumulateRectTransformBounds(
                    target,
                    cam,
                    originX,
                    originY,
                    clientH,
                    scaleX,
                    scaleY,
                    ref minX,
                    ref minY,
                    ref maxX,
                    ref maxY,
                    out var centerX,
                    out var centerY,
                    out var slotWidth,
                    out var slotHeight
                ))
                {
                    any = true;
                    rackSlots.Add(
                        new UiRackSlotSnapshot
                        {
                            rack_index = i,
                            x = Mathf.RoundToInt(centerX),
                            y = Mathf.RoundToInt(centerY),
                            width = Mathf.Max(1, Mathf.RoundToInt(slotWidth)),
                            height = Mathf.Max(1, Mathf.RoundToInt(slotHeight)),
                        }
                    );
                }
            }

            if (!any)
                return null;

            if (rackSlots.Count > 0)
            {
                var medianY = MedianSlotCenterY(rackSlots);
                var outlierCount = 0;
                for (var i = 0; i < rackSlots.Count; i++)
                {
                    var slot = rackSlots[i];
                    if (Mathf.Abs(slot.y - medianY) > 60f)
                    {
                        slot.y = Mathf.RoundToInt(medianY);
                        rackSlots[i] = slot;
                        outlierCount++;
                    }
                    minX = Mathf.Min(minX, slot.x);
                    minY = Mathf.Min(minY, slot.y);
                    maxX = Mathf.Max(maxX, slot.x);
                    maxY = Mathf.Max(maxY, slot.y);
                }
                if (outlierCount > 0)
                    LastStatus = "rack_slot_y_outlier";
            }

            if (RackSlotHorizontalSpan(rackSlots) < 100f)
            {
                if (RebuildRackSlotsFromSlotTransforms(
                    slots,
                    slotEnd,
                    cam,
                    originX,
                    originY,
                    clientH,
                    scaleX,
                    scaleY,
                    rackSlots
                ))
                {
                    LastStatus = "rack_slots_collapsed";
                    minX = float.MaxValue;
                    minY = float.MaxValue;
                    maxX = float.MinValue;
                    maxY = float.MinValue;
                    foreach (var slot in rackSlots)
                    {
                        minX = Mathf.Min(minX, slot.x);
                        minY = Mathf.Min(minY, slot.y);
                        maxX = Mathf.Max(maxX, slot.x);
                        maxY = Mathf.Max(maxY, slot.y);
                    }
                }
            }

            var rackWidth = Mathf.Max(1, Mathf.CeilToInt(maxX) - Mathf.FloorToInt(minX));
            if (rackWidth < 150 && rackSlots.Count >= 3)
                LastStatus = string.IsNullOrEmpty(LastStatus) ? "rack_bounds_narrow" : LastStatus;

            return new UiRackRectSnapshot
            {
                x = Mathf.FloorToInt(minX),
                y = Mathf.FloorToInt(minY),
                width = Mathf.Max(1, Mathf.CeilToInt(maxX) - Mathf.FloorToInt(minX)),
                height = Mathf.Max(1, Mathf.CeilToInt(maxY) - Mathf.FloorToInt(minY)),
                slot_count = rackSlots.Count > 0 ? rackSlots.Count : slotEnd,
                rack_slots = rackSlots,
            };
        }

        private static float MedianSlotCenterY(List<UiRackSlotSnapshot> slots)
        {
            if (slots == null || slots.Count == 0)
                return 0f;
            var ys = new float[slots.Count];
            for (var i = 0; i < slots.Count; i++)
                ys[i] = slots[i].y;
            Array.Sort(ys);
            return ys[ys.Length / 2];
        }

        private static float RackSlotHorizontalSpan(List<UiRackSlotSnapshot> slots)
        {
            if (slots == null || slots.Count == 0)
                return 0f;
            var minX = float.MaxValue;
            var maxX = float.MinValue;
            foreach (var slot in slots)
            {
                minX = Mathf.Min(minX, slot.x);
                maxX = Mathf.Max(maxX, slot.x);
            }
            return maxX - minX;
        }

        private static bool RebuildRackSlotsFromSlotTransforms(
            Transform[] slots,
            int slotEnd,
            Camera cam,
            int originX,
            int originY,
            int clientH,
            float scaleX,
            float scaleY,
            List<UiRackSlotSnapshot> rackSlots
        )
        {
            if (slots == null || slots.Length == 0 || rackSlots == null)
                return false;

            rackSlots.Clear();
            var any = false;
            for (var i = 0; i < slotEnd && i < slots.Length; i++)
            {
                var slotTransform = slots[i];
                if (slotTransform == null)
                    continue;

                if (!TryProjectTransformCenter(
                    slotTransform,
                    cam,
                    originX,
                    originY,
                    clientH,
                    scaleX,
                    scaleY,
                    out var centerX,
                    out var centerY
                ))
                    continue;

                any = true;
                rackSlots.Add(
                    new UiRackSlotSnapshot
                    {
                        rack_index = i,
                        x = Mathf.RoundToInt(centerX),
                        y = Mathf.RoundToInt(centerY),
                        width = 48,
                        height = 48,
                    }
                );
            }

            return any && RackSlotHorizontalSpan(rackSlots) >= 100f;
        }

        private static bool TryProjectTransformCenter(
            Transform transform,
            Camera cam,
            int originX,
            int originY,
            int clientH,
            float scaleX,
            float scaleY,
            out float centerX,
            out float centerY
        )
        {
            centerX = 0f;
            centerY = 0f;
            if (transform == null)
                return false;

            var rectTransform = transform as RectTransform;
            if (rectTransform != null)
            {
                var corners = new Vector3[4];
                rectTransform.GetWorldCorners(corners);
                var any = false;
                float minX = float.MaxValue;
                float minY = float.MaxValue;
                float maxX = float.MinValue;
                float maxY = float.MinValue;

                for (var i = 0; i < corners.Length; i++)
                {
                    if (!TryProjectWorldPoint(
                        corners[i],
                        cam,
                        originX,
                        originY,
                        clientH,
                        scaleX,
                        scaleY,
                        out var dx,
                        out var dy
                    ))
                        continue;
                    any = true;
                    minX = Mathf.Min(minX, dx);
                    minY = Mathf.Min(minY, dy);
                    maxX = Mathf.Max(maxX, dx);
                    maxY = Mathf.Max(maxY, dy);
                }

                if (!any)
                    return false;

                centerX = (minX + maxX) * 0.5f;
                centerY = (minY + maxY) * 0.5f;
                return true;
            }

            return TryProjectWorldPoint(
                transform.position,
                cam,
                originX,
                originY,
                clientH,
                scaleX,
                scaleY,
                out centerX,
                out centerY
            );
        }

        private static int ResolveConsumableSlotCount(InventoryVisualController ivc, int totalSlots)
        {
            if (IsSecondConsumableRowActive(ivc))
                return totalSlots;
            return Math.Min(FirstRowConsumableSlots, totalSlots);
        }

        private static bool IsSecondConsumableRowActive(InventoryVisualController ivc)
        {
            try
            {
                var field = typeof(InventoryVisualController).GetField(
                    "_secondRowTileParentGO",
                    MemberFlags
                );
                if (field == null)
                    return false;
                var go = field.GetValue(ivc) as GameObject;
                return go != null && go.activeSelf;
            }
            catch
            {
                return false;
            }
        }

        private static Transform[] GetTileSlotTransforms(InventoryVisualController ivc)
        {
            try
            {
                var field = typeof(InventoryVisualController).GetField(
                    "_tileSlotTransforms",
                    MemberFlags
                );
                if (field == null)
                    return null;
                return field.GetValue(ivc) as Transform[];
            }
            catch
            {
                return null;
            }
        }

        private static List<TileConsumableObject> GetConsumableTileObjects(InventoryVisualController ivc)
        {
            try
            {
                var field = typeof(InventoryVisualController).GetField(
                    "_consumableTileObjects",
                    MemberFlags
                );
                if (field == null)
                    return null;
                return field.GetValue(ivc) as List<TileConsumableObject>;
            }
            catch
            {
                return null;
            }
        }

        private static RectTransform GetConsumableRectTransform(TileConsumableObject consumable)
        {
            if (consumable == null)
                return null;
            try
            {
                var field = typeof(TileConsumableObject).GetField("_myRT", MemberFlags);
                if (field == null)
                    return null;
                return field.GetValue(consumable) as RectTransform;
            }
            catch
            {
                return null;
            }
        }

        private static Renderer[] GetTileRenderers(TileObject tileObject)
        {
            if (tileObject == null)
                return null;
            try
            {
                var field = typeof(TileObject).GetField("_tileRenderers", MemberFlags);
                if (field == null)
                    return null;
                return field.GetValue(tileObject) as Renderer[];
            }
            catch
            {
                return null;
            }
        }

        private static bool IsMainTileRenderer(Renderer renderer)
        {
            if (renderer == null || IsParticleRenderer(renderer))
                return false;
            var typeName = renderer.GetType().Name ?? "";
            if (typeName.IndexOf("Outline", StringComparison.OrdinalIgnoreCase) >= 0)
                return false;
            if (typeName.IndexOf("TextMesh", StringComparison.OrdinalIgnoreCase) >= 0)
                return false;
            return true;
        }

        private static bool TryProjectTileCenter(
            TileObject tileObject,
            Camera cam,
            int originX,
            int originY,
            int clientH,
            float scaleX,
            float scaleY,
            out float desktopX,
            out float desktopY
        )
        {
            desktopX = 0f;
            desktopY = 0f;
            if (tileObject == null)
                return false;

            float minX = float.MaxValue;
            float minY = float.MaxValue;
            float maxX = float.MinValue;
            float maxY = float.MinValue;
            var any = false;

            var renderers = GetTileRenderers(tileObject);
            if (renderers != null && renderers.Length > 0)
            {
                foreach (var renderer in renderers)
                {
                    if (AccumulateRendererBoundsProjected(
                        renderer,
                        cam,
                        originX,
                        originY,
                        clientH,
                        scaleX,
                        scaleY,
                        ref minX,
                        ref minY,
                        ref maxX,
                        ref maxY
                    ))
                        any = true;
                }
            }
            else
            {
                var fallback = tileObject.GetComponentsInChildren<Renderer>();
                if (fallback != null)
                {
                    foreach (var renderer in fallback)
                    {
                        if (!IsMainTileRenderer(renderer))
                            continue;
                        if (AccumulateRendererBoundsProjected(
                            renderer,
                            cam,
                            originX,
                            originY,
                            clientH,
                            scaleX,
                            scaleY,
                            ref minX,
                            ref minY,
                            ref maxX,
                            ref maxY
                        ))
                            any = true;
                    }
                }
            }

            if (any)
            {
                desktopX = (minX + maxX) * 0.5f;
                desktopY = (minY + maxY) * 0.5f;
                return true;
            }

            return TryProjectWorldPoint(
                tileObject.transform.position,
                cam,
                originX,
                originY,
                clientH,
                scaleX,
                scaleY,
                out desktopX,
                out desktopY
            );
        }

        private static bool AccumulateRendererBoundsProjected(
            Renderer renderer,
            Camera cam,
            int originX,
            int originY,
            int clientH,
            float scaleX,
            float scaleY,
            ref float minX,
            ref float minY,
            ref float maxX,
            ref float maxY
        )
        {
            if (renderer == null)
                return false;

            var bounds = renderer.bounds;
            var center = bounds.center;
            var extents = bounds.extents;
            var any = false;

            for (var xi = -1; xi <= 1; xi += 2)
            {
                for (var yi = -1; yi <= 1; yi += 2)
                {
                    for (var zi = -1; zi <= 1; zi += 2)
                    {
                        var corner = center + Vector3.Scale(extents, new Vector3(xi, yi, zi));
                        if (TryProjectWorldPoint(
                            corner,
                            cam,
                            originX,
                            originY,
                            clientH,
                            scaleX,
                            scaleY,
                            out var dx,
                            out var dy
                        ))
                        {
                            any = true;
                            minX = Mathf.Min(minX, dx);
                            minY = Mathf.Min(minY, dy);
                            maxX = Mathf.Max(maxX, dx);
                            maxY = Mathf.Max(maxY, dy);
                        }
                    }
                }
            }

            return any;
        }

        private static bool AccumulateRendererBoundsInChildren(
            Transform transform,
            Camera cam,
            int originX,
            int originY,
            int clientH,
            float scaleX,
            float scaleY,
            ref float minX,
            ref float minY,
            ref float maxX,
            ref float maxY
        )
        {
            var renderers = transform.GetComponentsInChildren<Renderer>();
            if (renderers == null || renderers.Length == 0)
                return false;

            var any = false;
            foreach (var renderer in renderers)
            {
                if (renderer == null || IsParticleRenderer(renderer))
                    continue;

                var bounds = renderer.bounds;
                var center = bounds.center;
                var extents = bounds.extents;

                for (var xi = -1; xi <= 1; xi += 2)
                {
                    for (var yi = -1; yi <= 1; yi += 2)
                    {
                        for (var zi = -1; zi <= 1; zi += 2)
                        {
                            var corner = center + Vector3.Scale(extents, new Vector3(xi, yi, zi));
                            if (AccumulateDesktopPoint(
                                corner,
                                cam,
                                originX,
                                originY,
                                clientH,
                                scaleX,
                                scaleY,
                                ref minX,
                                ref minY,
                                ref maxX,
                                ref maxY
                            ))
                                any = true;
                        }
                    }
                }
            }

            return any;
        }

        private static bool AccumulateRectTransformBounds(
            Transform transform,
            Camera cam,
            int originX,
            int originY,
            int clientH,
            float scaleX,
            float scaleY,
            ref float minX,
            ref float minY,
            ref float maxX,
            ref float maxY,
            out float centerX,
            out float centerY,
            out float slotWidth,
            out float slotHeight
        )
        {
            centerX = 0f;
            centerY = 0f;
            slotWidth = 0f;
            slotHeight = 0f;
            if (transform == null)
                return false;

            var rectTransform = transform as RectTransform;
            if (rectTransform != null)
            {
                var corners = new Vector3[4];
                rectTransform.GetWorldCorners(corners);
                var any = false;
                float localMinX = float.MaxValue;
                float localMinY = float.MaxValue;
                float localMaxX = float.MinValue;
                float localMaxY = float.MinValue;

                for (var i = 0; i < corners.Length; i++)
                {
                    if (TryProjectWorldPoint(
                        corners[i],
                        cam,
                        originX,
                        originY,
                        clientH,
                        scaleX,
                        scaleY,
                        out var dx,
                        out var dy
                    ))
                    {
                        any = true;
                        localMinX = Mathf.Min(localMinX, dx);
                        localMinY = Mathf.Min(localMinY, dy);
                        localMaxX = Mathf.Max(localMaxX, dx);
                        localMaxY = Mathf.Max(localMaxY, dy);
                        minX = Mathf.Min(minX, dx);
                        minY = Mathf.Min(minY, dy);
                        maxX = Mathf.Max(maxX, dx);
                        maxY = Mathf.Max(maxY, dy);
                    }
                }

                if (any)
                {
                    centerX = (localMinX + localMaxX) * 0.5f;
                    centerY = (localMinY + localMaxY) * 0.5f;
                    slotWidth = localMaxX - localMinX;
                    slotHeight = localMaxY - localMinY;
                }

                return any;
            }

            float fbMinX = float.MaxValue;
            float fbMinY = float.MaxValue;
            float fbMaxX = float.MinValue;
            float fbMaxY = float.MinValue;
            var anyFallback = false;
            var renderers = transform.GetComponentsInChildren<Renderer>();
            if (renderers != null)
            {
                foreach (var renderer in renderers)
                {
                    if (AccumulateRendererBoundsProjected(
                        renderer,
                        cam,
                        originX,
                        originY,
                        clientH,
                        scaleX,
                        scaleY,
                        ref fbMinX,
                        ref fbMinY,
                        ref fbMaxX,
                        ref fbMaxY
                    ))
                        anyFallback = true;
                }
            }

            if (anyFallback)
            {
                centerX = (fbMinX + fbMaxX) * 0.5f;
                centerY = (fbMinY + fbMaxY) * 0.5f;
                slotWidth = fbMaxX - fbMinX;
                slotHeight = fbMaxY - fbMinY;
                minX = Mathf.Min(minX, fbMinX);
                minY = Mathf.Min(minY, fbMinY);
                maxX = Mathf.Max(maxX, fbMaxX);
                maxY = Mathf.Max(maxY, fbMaxY);
                return true;
            }

            if (TryProjectWorldPoint(
                transform.position,
                cam,
                originX,
                originY,
                clientH,
                scaleX,
                scaleY,
                out centerX,
                out centerY
            ))
            {
                minX = Mathf.Min(minX, centerX);
                minY = Mathf.Min(minY, centerY);
                maxX = Mathf.Max(maxX, centerX);
                maxY = Mathf.Max(maxY, centerY);
                return true;
            }

            return false;
        }

        private static bool IsParticleRenderer(Renderer renderer)
        {
            return renderer != null
                && string.Equals(
                    renderer.GetType().Name,
                    "ParticleSystemRenderer",
                    StringComparison.Ordinal
                );
        }

        private static bool TryProjectWorldPoint(
            Vector3 worldPoint,
            Camera cam,
            int originX,
            int originY,
            int clientH,
            float scaleX,
            float scaleY,
            out float desktopX,
            out float desktopY
        )
        {
            desktopX = 0f;
            desktopY = 0f;
            var screen = cam.WorldToScreenPoint(worldPoint);
            if (screen.z < 0f)
                return false;

            desktopX = originX + screen.x * scaleX;
            desktopY = originY + (clientH - screen.y * scaleY);
            return true;
        }

        private static bool AccumulateDesktopPoint(
            Vector3 worldPoint,
            Camera cam,
            int originX,
            int originY,
            int clientH,
            float scaleX,
            float scaleY,
            ref float minX,
            ref float minY,
            ref float maxX,
            ref float maxY
        )
        {
            if (!TryProjectWorldPoint(
                worldPoint,
                cam,
                originX,
                originY,
                clientH,
                scaleX,
                scaleY,
                out var desktopX,
                out var desktopY
            ))
                return false;

            minX = Mathf.Min(minX, desktopX);
            minY = Mathf.Min(minY, desktopY);
            maxX = Mathf.Max(maxX, desktopX);
            maxY = Mathf.Max(maxY, desktopY);
            return true;
        }
    }
}
