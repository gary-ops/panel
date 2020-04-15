import * as p from "@bokehjs/core/properties"
import {PanelHTMLBoxView} from "../layout"
import {AbstractVTKView, AbstractVTKPlot} from "./vtk_layout"

import {div} from "@bokehjs/core/dom"
import {set_size} from "../layout"
import {FullScreenRenderWindowSynchronized} from "./panel_fullscreen_renwin_sync"
import {vtkns} from "./vtk_utils"

const CONTEXT_NAME = "panel"

export class VTKSynchronizedPlotView extends AbstractVTKView {
  model: VTKSynchronizedPlot
  protected _synchronizer_context: any
  protected _arrays: any
  protected _decoded_arrays: any
  protected _pending_arrays: any
  protected _camera_callbacks: any[]
  public getArray: CallableFunction
  public registerArray: CallableFunction

  initialize(): void {
    super.initialize()
    this._camera_callbacks = []
    this._arrays = {}
    this._decoded_arrays = {}
    this._pending_arrays = {}
    // Internal closures
    this.getArray = (hash: string) => {
      if (this._arrays[hash]) {
        return Promise.resolve(this._arrays[hash])
      }

      return new Promise((resolve, reject) => {
        this._pending_arrays[hash] = {resolve, reject}
      })
    }

    this.registerArray = (hash: string, array: any) => {
      this._arrays[hash] = array
      if (this._pending_arrays[hash]) {
        this._pending_arrays[hash].resolve(array)
      }
      return true
    }

    // Context initialisation
    this._synchronizer_context = vtkns.SynchronizableRenderWindow.getSynchronizerContext(
      CONTEXT_NAME
    )
  }

  render(): void {
    PanelHTMLBoxView.prototype.render.call(this) // super.super.render()
    this._orientationWidget = null
    let renderer = null
    if (this._vtk_renwin) {
      renderer = this._vtk_renwin.getRenderer()
    } else {
      this._vtk_container = div()
    }
    this._vtk_renwin = FullScreenRenderWindowSynchronized.newInstance({
      rootContainer: this.el,
      container: this._vtk_container,
      synchronizerContext: this._synchronizer_context,
    })
    set_size(this._vtk_container, this.model)
    this.el.appendChild(this._vtk_container)
    if (!renderer) {
      this._vtk_renwin.getRenderWindow().clearOneTimeUpdaters()
      this._decode_arrays()
      this._plot()
    } else {
      this._vtk_renwin.getRenderWindow().addRenderer(renderer)
    }
    this._remove_default_key_binding()
    this._bind_key_events()
    this._create_orientation_widget()
    this._set_camera_state()
    this._set_axes()
    this.model.renderer_el = this._vtk_renwin
  }

  _decode_arrays(): void {
    const jszip = new (window as any).JSZip()
    const promises: any = []
    const arrays: any = this.model.arrays
    const registerArray: any = this.registerArray
    const arrays_processed = this.model.arrays_processed

    function load(key: string) {
      return jszip
        .loadAsync(atob(arrays[key]))
        .then((zip: any) => zip.file("data/" + key))
        .then((zipEntry: any) => zipEntry.async("arraybuffer"))
            .then((arraybuffer: any) => registerArray(key, arraybuffer))
        .then(() => arrays_processed.push(key))
    }

    Object.keys(arrays).forEach((key: string) => {
      if (!this._decoded_arrays[key]) {
        this._decoded_arrays[key] = true
        promises.push(load(key))
        }
    })
    Promise.all(promises).then(() => {
      this.model.arrays_processed = [...this.model.arrays_processed]
    })
  }

  _unsubscribe_camera_cb(): void {
    this._camera_callbacks
      .splice(0, this._camera_callbacks.length)
      .map((cb) => cb.unsubscribe())
  }

  _plot(): void {
    this._synchronizer_context.setFetchArrayFunction(this.getArray)
    this._unsubscribe_camera_cb()
    const renderer = this._synchronizer_context.getInstance(
      this.model.scene.dependencies[0].id
    )
    if (renderer && !this._vtk_renwin.getRenderer()) {
      this._vtk_renwin.getRenderWindow().addRenderer(renderer)
    }
    this._vtk_renwin
      .getRenderWindow()
      .setSynchronizedViewId(this.model.scene.id)
    this._vtk_renwin.getRenderWindow().synchronize(this.model.scene)
    this._camera_callbacks.push(
      this._vtk_renwin
        .getRenderer()
        .getActiveCamera()
        .onModified(() => {
          this._get_camera_state()
          this._vtk_render()
        })
    )
    //hack to handle the orientation widget when synchronized
    if (this._orientationWidget){
      this._orientationWidget.setEnabled(false)
      this._orientationWidget.setEnabled(this.model.orientation_widget)
    }
  }

  remove(): void {
    this._unsubscribe_camera_cb()
    super.remove()
  }

  connect_signals(): void {
    super.connect_signals()
    this.connect(this.model.properties.arrays.change, () =>
      this._decode_arrays()
    )
    this.connect(this.model.properties.scene.change, () => {
      this._plot()
      this._vtk_render()
    })
    this.connect(this.model.properties.one_time_reset.change, () => {
      this._vtk_renwin.getRenderWindow().clearOneTimeUpdaters()
    })
  }
}

export namespace VTKSynchronizedPlot {
  export type Attrs = p.AttrsOf<Props>
  export type Props = AbstractVTKPlot.Props & {
    arrays: p.Property<any>
    arrays_processed: p.Property<string[]>
    one_time_reset: p.Property<boolean>
    scene: p.Property<any>
  }
}

export interface VTKSynchronizedPlot extends VTKSynchronizedPlot.Attrs {}

export class VTKSynchronizedPlot extends AbstractVTKPlot {
  properties: VTKSynchronizedPlot.Props
  renderer_el: any

  static __module__ = "panel.models.vtk"

  constructor(attrs?: Partial<VTKSynchronizedPlot.Attrs>) {
    super(attrs)
    this.renderer_el = null
  }

  getActors(): [any] {
    return this.renderer_el.getRenderer().getActors()
  }

  static init_VTKSynchronizedPlot(): void {
    this.prototype.default_view = VTKSynchronizedPlotView

    this.define<VTKSynchronizedPlot.Props>({
      arrays:             [ p.Any,        {} ],
      arrays_processed:   [ p.Array,      [] ],
      axes:               [ p.Instance       ],
      enable_keybindings: [ p.Boolean, false ],
      one_time_reset:     [ p.Boolean        ],
      scene:              [ p.Any,        {} ],
    })

    this.override({
      height: 300,
      width: 300,
    })
  }
}
