import { Component, Entity, type Handle, MotorComponent, PhysicsComponent, Icon, ForceSpace, Vec3, HandleArray } from "prototwin";

@Icon("material-symbols:drone-outline")
export class Drone extends Component {
    @HandleArray(Entity)
    public rotors: Handle<Entity>[] = [];

    constructor(entity: Entity) {
        super(entity);
    }

    public applyForce(rotor: Handle<Entity>, body: PhysicsComponent): void {
        const entity = rotor.value;
        if (entity !== null) {
            const motor = entity.component(MotorComponent);
            const physics = entity.component(PhysicsComponent);
            const joint = physics.joints![0];
            const point = entity.localToWorldPoint(joint.anchor);
            const axis = entity.worldRotation.yaxis;
            const speed = Math.abs(motor.currentVelocity);
            const force = Vec3.scaleUniform(axis, speed * 0.05);
            body.applyForceAtPoint(force, point, ForceSpace.World);
        }
    }

    public override update(dt: number): void {
        const body = this.entity.component(PhysicsComponent);
        for (const rotor of this.rotors) {
            this.applyForce(rotor, body);
        }
    }
}
