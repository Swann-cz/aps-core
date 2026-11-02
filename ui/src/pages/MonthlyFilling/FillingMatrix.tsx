import { Table } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { useRef, useState } from 'react'

export function FillingMatrix({
  columns,
  dataSource,
}: {
  columns: ColumnsType<any>
  dataSource: any[]
}) {
  const rootRef = useRef<HTMLDivElement>(null)
  const dragRef = useRef<{
    pointerId: number
    startX: number
    startScrollLeft: number
    dragged: boolean
  } | null>(null)
  const suppressClickRef = useRef(false)
  const [dragging, setDragging] = useState(false)

  const scrollNode = () => rootRef.current?.querySelector<HTMLElement>('.ant-table-content') ?? null
  const ignoreDragTarget = (target: EventTarget | null) => {
    if (!(target instanceof HTMLElement)) return true
    return Boolean(target.closest('input, textarea, .ant-input-number, .ant-select, .ant-picker, .ant-btn'))
  }

  return (
    <div
      ref={rootRef}
      className={`filling-matrix${dragging ? ' is-dragging' : ''}`}
      data-testid="filling-matrix"
      onPointerDown={(event) => {
        if (event.button !== 0 || ignoreDragTarget(event.target)) return
        const scroll = scrollNode()
        if (!scroll) return
        dragRef.current = {
          pointerId: event.pointerId,
          startX: event.clientX,
          startScrollLeft: scroll.scrollLeft,
          dragged: false,
        }
      }}
      onPointerMove={(event) => {
        const drag = dragRef.current
        if (!drag || drag.pointerId !== event.pointerId) return
        const delta = event.clientX - drag.startX
        if (!drag.dragged && Math.abs(delta) > 5) {
          drag.dragged = true
          setDragging(true)
          event.currentTarget.setPointerCapture(event.pointerId)
        }
        if (!drag.dragged) return
        const scroll = scrollNode()
        if (scroll) scroll.scrollLeft = drag.startScrollLeft - delta
        event.preventDefault()
      }}
      onPointerUp={(event) => {
        const drag = dragRef.current
        if (!drag || drag.pointerId !== event.pointerId) return
        suppressClickRef.current = drag.dragged
        if (drag.dragged) window.setTimeout(() => { suppressClickRef.current = false }, 0)
        dragRef.current = null
        setDragging(false)
        if (event.currentTarget.hasPointerCapture(event.pointerId)) {
          event.currentTarget.releasePointerCapture(event.pointerId)
        }
      }}
      onPointerCancel={() => {
        dragRef.current = null
        setDragging(false)
      }}
      onClickCapture={(event) => {
        if (!suppressClickRef.current) return
        suppressClickRef.current = false
        event.preventDefault()
        event.stopPropagation()
      }}
    >
      <Table
        className="filling-table"
        size="small"
        bordered
        rowKey="key"
        columns={columns}
        dataSource={dataSource}
        pagination={false}
        scroll={{ x: 2900 }}
      />
    </div>
  )
}
