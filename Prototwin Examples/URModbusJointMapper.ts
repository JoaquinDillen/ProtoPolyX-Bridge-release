import { Access, Component, DoubleSignal, Icon, IO, type Entity } from "prototwin";

export class URModbusJointMapperIO extends IO {
    public rawJ1: DoubleSignal;
    public rawJ2: DoubleSignal;
    public rawJ3: DoubleSignal;
    public rawJ4: DoubleSignal;
    public rawJ5: DoubleSignal;
    public rawJ6: DoubleSignal;
    public rawGripper: DoubleSignal;

    public targetJ1: DoubleSignal;
    public targetJ2: DoubleSignal;
    public targetJ3: DoubleSignal;
    public targetJ4: DoubleSignal;
    public targetJ5: DoubleSignal;
    public targetJ6: DoubleSignal;
    public targetLeftFinger: DoubleSignal;
    public targetRightFinger: DoubleSignal;

    public constructor() {
        super();

        this.rawJ1 = new DoubleSignal(10000, Access.Writable);
        this.rawJ2 = new DoubleSignal(10000, Access.Writable);
        this.rawJ3 = new DoubleSignal(10000, Access.Writable);
        this.rawJ4 = new DoubleSignal(10000, Access.Writable);
        this.rawJ5 = new DoubleSignal(10000, Access.Writable);
        this.rawJ6 = new DoubleSignal(10000, Access.Writable);
        this.rawGripper = new DoubleSignal(0, Access.Writable);

        this.targetJ1 = new DoubleSignal(0, Access.Readable);
        this.targetJ2 = new DoubleSignal(0, Access.Readable);
        this.targetJ3 = new DoubleSignal(0, Access.Readable);
        this.targetJ4 = new DoubleSignal(0, Access.Readable);
        this.targetJ5 = new DoubleSignal(0, Access.Readable);
        this.targetJ6 = new DoubleSignal(0, Access.Readable);
        this.targetLeftFinger = new DoubleSignal(0, Access.Readable);
        this.targetRightFinger = new DoubleSignal(0, Access.Readable);
    }
}

@Icon("material-symbols:precision-manufacturing-outline")
export class URModbusJointMapper extends Component {
    #io: URModbusJointMapperIO;

    public rawCenter = 10000;
    public ticksPerDegree = 10;

    public dirJ1 = -1;
    public dirJ2 = 1;
    public dirJ3 = -1;
    public dirJ4 = 1;
    public dirJ5 = -1;
    public dirJ6 = 1;

    public offsetJ1 = 0;
    public offsetJ2 = 0;
    public offsetJ3 = 0;
    public offsetJ4 = 0;
    public offsetJ5 = 0;
    public offsetJ6 = 0;
    public gripperRawScale = 10000;
    public leftFingerDirection = 1;
    public rightFingerDirection = 1;

    public override get io(): URModbusJointMapperIO {
        return this.#io;
    }

    public override set io(value: URModbusJointMapperIO) {
        this.#io = value;
    }

    public constructor(entity: Entity) {
        super(entity);
        this.#io = new URModbusJointMapperIO();
    }

    public override update(dt: number): void {
        this.#io.targetJ1.value = this.decode(this.#io.rawJ1.value, this.dirJ1, this.offsetJ1);
        this.#io.targetJ2.value = this.decode(this.#io.rawJ2.value, this.dirJ2, this.offsetJ2);
        this.#io.targetJ3.value = this.decode(this.#io.rawJ3.value, this.dirJ3, this.offsetJ3);
        this.#io.targetJ4.value = this.decode(this.#io.rawJ4.value, this.dirJ4, this.offsetJ4);
        this.#io.targetJ5.value = this.decode(this.#io.rawJ5.value, this.dirJ5, this.offsetJ5);
        this.#io.targetJ6.value = this.decode(this.#io.rawJ6.value, this.dirJ6, this.offsetJ6);

        const gripperPosition = this.#io.rawGripper.value / this.gripperRawScale;
        this.#io.targetLeftFinger.value = gripperPosition * this.leftFingerDirection;
        this.#io.targetRightFinger.value = gripperPosition * this.rightFingerDirection;
    }

    private decode(rawValue: number, direction: number, offset: number): number {
        const degrees = (rawValue - this.rawCenter) / this.ticksPerDegree;
        return direction * degrees * Math.PI / 180 + offset;
    }
}
