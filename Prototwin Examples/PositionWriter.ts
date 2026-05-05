import { Component, type Entity, IO, FloatSignal, Access, Icon, Vec3 } from "prototwin";

export class PositionWriterIO extends IO {
    public x: FloatSignal;
    public y: FloatSignal;
    public z: FloatSignal;

    public constructor() {
        super();
        this.x = new FloatSignal(0, Access.Writable);
        this.y = new FloatSignal(0, Access.Writable);
        this.z = new FloatSignal(0, Access.Writable);
    }
}

@Icon("game-icons:position-marker")
export class PositionWriter extends Component {
    #io: PositionWriterIO;

    public override get io(): PositionWriterIO {
        return this.#io;
    }

    constructor(entity: Entity) {
        super(entity);
        this.#io = new PositionWriterIO();
    }

    public override update(dt: number): void {
        const p = this.entity.position;
        const x = this.#io.x.value;
        const y = this.#io.y.value;
        const z = this.#io.z.value;
        if (p.x !== x || p.y !== y || p.z !== z) {
            this.entity.position = new Vec3(x, y, z);
        }
    }
}
