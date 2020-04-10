import * as p from "@bokehjs/core/properties"
import {PanelHTMLBoxView} from "../layout"
import {AbstractVTKView, AbstractVTKPlot} from "./vtk_layout"

import {div} from "@bokehjs/core/dom"
import {set_size} from "../layout"
import {FullScreenRenderWindowSynchronized} from "./panel_fullscreen_renwin_sync"
import { vtkns } from "./vtk_utils"

export class VTKSynchronizedPlotView extends AbstractVTKView {
  model: VTKSynchronizedPlot
  protected _context_name: string
  protected _synchronizer_context: any
  protected _arrays: any
  protected _decoded_arrays: any
  protected _pending_arrays: any
  protected _camera_callback: any
  public getArray: CallableFunction
  public registerArray: CallableFunction

  initialize(): void {
    super.initialize()
    if(this.model.context_name !== ''){
      this._context_name = this.model.context_name
    } else {
      this._context_name = Math.random().toString(36).slice(2)
    }
    this._arrays = {};
    this._decoded_arrays = {};
    this._pending_arrays = {};
    // Internal closures
    this.getArray = (hash: string) => {
      if (this._arrays[hash]) {
          return Promise.resolve(this._arrays[hash]);
      }

      return new Promise((resolve, reject) => {
        this._pending_arrays[hash] = { resolve, reject };
      });
    };

    this.registerArray = (hash: string, array: any) =>
    {
      this._arrays[hash] = array;
      if (this._pending_arrays[hash]) {
          this._pending_arrays[hash].resolve(array);
      }
      return true;
    };

    // Context initialisation
    this._synchronizer_context = vtkns.SynchronizableRenderWindow.getSynchronizerContext(
      this._context_name
    )
  }

  render(): void {
    console.log('render start')
    PanelHTMLBoxView.prototype.render.call(this) // super.super.render()
    this._orientationWidget = null
    this._vtk_container = div()
    set_size(this._vtk_container, this.model)
    this.el.appendChild(this._vtk_container)
    let renderer = null
    if(this._vtk_renwin){
      renderer = this._vtk_renwin.getRenderer()
    }
    this._vtk_renwin = FullScreenRenderWindowSynchronized.newInstance({
      rootContainer: this.el,
      container: this._vtk_container,
      synchronizerContext: this._synchronizer_context
    })
    
    if(!renderer) {
      this._vtk_renwin.getRenderWindow().clearOneTimeUpdaters()
      this._decode_arrays()
      this._plot()
    } else {
      this._vtk_renwin.getRenderWindow().addRenderer(renderer)
    }
    this._remove_default_key_binding()
    // this._create_orientation_widget()
    // this._orientationWidget.updateMarkerOrientation()
    this._vtk_renwin.getRenderer().resetCameraClippingRange()
    this._vtk_renwin.getRenderWindow().render()
    this.model.renderer_el = this._vtk_renwin
    console.log('render end')
  }

  after_layout(): void {
    console.log('after layout start')
    super.after_layout()
    console.log('after layout end')
  }

  _decode_arrays(): void {
    console.log('decode arrays start')
    const jszip = new (window as any).JSZip();
    const promises: any = [];
    const arrays: any = this.model.arrays;
    const registerArray: any = this.registerArray;
    const arrays_processed = this.model.arrays_processed;

    function load(key: string) {
        return jszip.loadAsync(atob(arrays[key]))
            .then((zip: any) => zip.file('data/' + key))
            .then((zipEntry: any) => zipEntry.async('arraybuffer'))
            .then((arraybuffer: any) => registerArray(key, arraybuffer))
            .then(() => arrays_processed.push(key));
    }

    Object.keys(arrays).forEach((key: string) => {
        if (!this._decoded_arrays[key])
        {
            this._decoded_arrays[key] = true;
            promises.push(load(key));
        }
    })
    console.log('decode arrays end')
  }

  _plot(): void{
    console.log('plot start')
    if(this._camera_callback){
      this._camera_callback.unsubscribe()
    }
    this._synchronizer_context.setFetchArrayFunction(this.getArray)
    const renderer = this._synchronizer_context.getInstance(this.model.scene.dependencies[0].id)
    if(renderer && !this._vtk_renwin.getRenderer()){
      this._vtk_renwin.getRenderWindow().addRenderer(renderer)
    }
    this._vtk_renwin.getRenderWindow().setSynchronizedViewId(this.model.scene.id)
    this._vtk_renwin.getRenderWindow().synchronize(this.model.scene)
    this._vtk_renwin.getRenderWindow().render()

    if(this._camera_callback){
      this._camera_callback.unsubscribe()
      this._camera_callback = null
    }
    this._camera_callback = this._vtk_renwin.getRenderer().getActiveCamera().onModified(
      () => {
          if(this._orientationWidget)
            this._orientationWidget.updateMarkerOrientation()
          this._vtk_renwin.getInteractor().render()
      }
    )
    
    console.log('plot end')
  }

  remove(): void {
    console.log('remove start')
    if(this._camera_callback){
      this._camera_callback.unsubscribe()
      this._camera_callback = null
    }
    super.remove()
    console.log('remove end')
  }

  connect_signals(): void {
    PanelHTMLBoxView.prototype.connect_signals.call(this) //super.super.connec_signals
    this.connect(this.model.properties.orientation_widget.change, () => {
      this._orientation_widget_visibility(this.model.orientation_widget)
    })
    this.connect(this.model.properties.arrays.change, () => this._decode_arrays())
    this.connect(this.model.properties.scene.change, () => {
      this._plot()
    })
    this.connect(this.model.properties.one_time_reset.change, () => {
      this._vtk_renwin.getRenderWindow().clearOneTimeUpdaters()
    })
    this.el.addEventListener('mouseenter', () => {
      const interactor = this._vtk_renwin.getInteractor()
      if(this.model.enable_keybindings){
        document.querySelector('body')!.addEventListener('keypress',interactor.handleKeyPress)
        document.querySelector('body')!.addEventListener('keydown',interactor.handleKeyDown)
        document.querySelector('body')!.addEventListener('keyup',interactor.handleKeyUp)
      }
    })
    this.el.addEventListener('mouseleave', () => {
      const interactor = this._vtk_renwin.getInteractor()
      document.querySelector('body')!.removeEventListener('keypress',interactor.handleKeyPress)
      document.querySelector('body')!.removeEventListener('keydown',interactor.handleKeyDown)
      document.querySelector('body')!.removeEventListener('keyup',interactor.handleKeyUp)
    })

  }
}

export namespace VTKSynchronizedPlot {
  export type Attrs = p.AttrsOf<Props>
  export type Props = AbstractVTKPlot.Props & {
    scene: p.Property<any>
    arrays: p.Property<any>
    arrays_processed: p.Property<string[]>
    enable_keybindings: p.Property<boolean>
    context_name: p.Property<string>
    one_time_reset: p.Property<boolean>
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

  getActors() : [any] {
    return this.renderer_el.getRenderer().getActors()
  }

  static init_VTKSynchronizedPlot(): void {
    this.prototype.default_view = VTKSynchronizedPlotView

    this.define<VTKSynchronizedPlot.Props>({
      scene:              [ p.Any, {}        ],
      arrays:             [ p.Any, {}        ],
      arrays_processed:   [ p.Array, []      ],
      enable_keybindings: [ p.Boolean, false ],
      context_name:       [ p.String, ''     ],
      one_time_reset:     [ p.Boolean        ],
    })

    this.override({
      height: 300,
      width: 300
    })
  }
}